from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

from src.world.clock import TimeState
from src.agents.role_agent import RoleAgent
from src.config import get_world_config
from src.world.scheduling import Schedule
from src.world.god import env_and_nsp, split_response_by_visible_blocks
from src.agents.prompts import END_SIGN
from src.utils import clip_str
from src.world.scheduling import make_activity_id


@dataclass
class Activity:
    """Base activity with minimal execution hooks.

    activity_id can be None for subclasses that auto-generate it in __post_init__.
    """

    activity_id: Optional[str]
    activity_name: str
    time: TimeState
    agents: List[RoleAgent]

    def run(self) -> None:
        """Execute the activity. Subclasses implement details."""
        raise NotImplementedError("Subclasses must implement run()")

    def _format_outcome_message(self, outcome: object) -> str:
        """Format outcome into a message for agent to receive.

        Works for both JointActivityOutcome and ActionOutcome (Solo).

        Args:
            outcome: JointActivityOutcome or ActionOutcome instance

        Returns:
            Formatted message string
        """
        lines = ["## Activity Outcome", ""]

        # Vitality
        delta_vitality = getattr(outcome, "delta_vitality", 0)
        if delta_vitality != 0:
            sign = "+" if delta_vitality > 0 else ""
            lines.append(f"- Vitality: {sign}{delta_vitality}")

        # Fulfillment
        delta_fulfillment = getattr(outcome, "delta_fulfillment", {})
        if delta_fulfillment:
            for key, delta in sorted(delta_fulfillment.items()):
                if delta != 0:
                    sign = "+" if delta > 0 else ""
                    key_name = key.capitalize()
                    lines.append(f"- {key_name}: {sign}{delta}")

        # Skills
        delta_skills = getattr(outcome, "delta_skills", {})
        if delta_skills:
            for skill, delta in sorted(delta_skills.items()):
                if delta != 0:
                    sign = "+" if delta > 0 else ""
                    lines.append(f"- Skill '{skill}': {sign}{delta}")

        # Money (Solo only)
        delta_money = getattr(outcome, "delta_money", 0)
        if delta_money != 0:
            sign = "+" if delta_money > 0 else ""
            lines.append(f"- Money: {sign}{delta_money}")

        # Items received (Joint)
        items_received = getattr(outcome, "items_received", [])
        if items_received:
            for item in items_received:
                lines.append(f"- Received item '{item['name']}' from {item['from']}")

        # Items sent (Joint)
        items_sent = getattr(outcome, "items_sent", [])
        if items_sent:
            for item in items_sent:
                lines.append(f"- Gave away item '{item['name']}' to {item['to']}")

        # Items gained (Solo)
        gain_items = getattr(outcome, "gain_items", [])
        if gain_items:
            for item in gain_items:
                lines.append(f"- Gained item: '{item['name']}'")

        if len(lines) == 2:  # Only header and empty line, no changes
            lines.append("- No significant changes")

        return "\n".join(lines)


@dataclass
class JointActivity(Activity):
    """Multi-person interactive activity (dialog-like turns)."""

    # Keep the full Schedule as single source of truth for proposer/actions/etc.
    schedule: Schedule
    location_store: Optional[object] = None  # Injected dependency

    @classmethod
    def from_schedule(
        cls, schd: Schedule, agents: List[RoleAgent], location_store
    ) -> "JointActivity":
        """Construct a JointActivity from a Schedule and agents list."""
        return cls(
            activity_id=schd.activity_id,
            activity_name=schd.activity_name,
            time=schd.activity_time,
            agents=agents,
            schedule=schd,
            location_store=location_store,
        )

    def _parse_gift_actions(
        self, response: str, sender_name: str
    ) -> Tuple[List[Tuple[str, str, str]], Dict[str, str]]:
        """Parse <role_action>gift(...)</role_action> from response.

        Args:
            response: Agent's response text
            sender_name: Name of the agent who sent the response

        Returns:
            Tuple of (gifts, errs):
                - gifts: List of (sender_name, receiver_name, item_name) 3-tuples
                  (item_description is not available at parse time; added after _exec_gift)
                - errs: Dict of {action_string: error_message} for parse errors
        """
        import re

        from src.utils import extract_role_action_blocks, parse_kv_args

        gifts: List[Tuple[str, str, str]] = []
        errs: Dict[str, str] = {}
        blocks = extract_role_action_blocks(response)

        for blk in blocks:
            s = blk.strip()
            # Match action_name(args)
            m = re.match(r"\s*(\w+)\s*\(\s*(.*)\s*\)\s*\Z", s, flags=re.DOTALL)
            if not m:
                errs[s] = "unparsable role_action block"
                continue

            act = m.group(0)
            act_type = m.group(1).lower()
            if act_type != "gift":
                continue

            args_raw = m.group(2)
            try:
                args = parse_kv_args(args_raw)
                to = str(args.get("to", "")).strip()
                item = str(args.get("item", "")).strip()

                if not to or not item:
                    errs[act] = "gift action missing required params: to and item"
                    continue

                gifts.append((sender_name, to, item))
            except Exception as e:
                errs[act] = f"bad args for gift action: {e}"
                continue

        return gifts, errs

    def _parse_exit_action(self, response: str) -> bool:
        """Check if response contains exit_activity() action.

        Args:
            response: Agent's response text

        Returns:
            True if exit_activity() action found, False otherwise
        """
        import re

        from src.utils import extract_role_action_blocks

        for blk in extract_role_action_blocks(response):
            s = blk.strip().lower()
            if re.match(r"exit_activity\s*\(\s*\)", s):
                return True
        return False

    def _exec_gift(
        self,
        sender_name: str,
        receiver_name: str,
        item_name: str,
        agent_possessions: Dict[str, List[Dict]],
    ) -> Tuple[bool, str, Optional[str], str]:
        """Execute a gift transfer immediately (modifies state).

        Args:
            sender_name: Name of the agent giving the gift
            receiver_name: Name of the agent receiving the gift
            item_name: Name of the item to transfer
            agent_possessions: In-memory possessions map for all agents in this activity

        Returns:
            Tuple of (success, notification_sender, notification_receiver, item_description):
                - success: True if gift executed successfully, False otherwise
                - notification_sender: System notification for sender (error message if failed)
                - notification_receiver: System notification for receiver (None if failed)
                - item_description: Description of the item (empty string if failed)
        """
        agent_by_name = {ag.name: ag for ag in self.agents}
        participants = set(agent_by_name.keys())

        # Validate cannot gift to self
        if sender_name == receiver_name:
            error_msg = f"System Notification: You attempted to give '{item_name}' to yourself, but this is not allowed."
            return False, error_msg, None, ""

        # Validate receiver exists and is a participant
        if receiver_name not in participants:
            error_msg = (
                f"System Notification: You attempted to give '{item_name}' to {receiver_name}, "
                f"but {receiver_name} is not a participant in this activity."
            )
            return False, error_msg, None, ""

        sender_agent = agent_by_name[sender_name]
        receiver_agent = agent_by_name[receiver_name]

        # Validate sender owns the item: read from in-memory possessions
        possessions = agent_possessions[sender_name]
        item_to_transfer = None
        item_index = None

        for idx, item in enumerate(possessions):
            if item["name"] == item_name:
                item_to_transfer = item
                item_index = idx
                break

        if item_to_transfer is None:
            error_msg = (
                f"System Notification: You attempted to give '{item_name}' to {receiver_name}, "
                f"but you don't own this item."
            )
            return False, error_msg, None, ""

        # Execute the transfer: remove from sender, add to receiver
        item_description = item_to_transfer.get("description", "")

        # Remove from sender's possessions (in-memory only, will be written in APPLY phase)
        possessions.pop(item_index)

        # Add to receiver's possessions (in-memory only, will be written in APPLY phase)
        receiver_possessions = agent_possessions[receiver_name]
        receiver_possessions.append(
            {
                "name": item_name,
                "description": item_description,
            }
        )

        # Generate system notifications with descriptions
        notification_sender = f"System Notification: You gave '{item_name}' ({item_description}) to {receiver_name}."
        notification_receiver = f"System Notification: You received '{item_name}' ({item_description}) from {sender_name}."

        return True, notification_sender, notification_receiver, item_description

    def run(self) -> None:
        from src.utils import get_verify_logger, save_feature_generation

        # VERIFY_FEATURE: joint_activity
        logger = get_verify_logger(feature="joint_activity")

        cfg = get_world_config()
        min_turns = int(cfg["activity"]["joint_activity_min_turns"])
        max_turns = int(cfg["activity"]["joint_activity_max_turns"])

        # Get location description at activity start
        location_desc = (
            self.location_store.get_surroundings_text(self.schedule.location)
            if self.schedule.location
            else ""
        )

        schd = self.schedule
        # Build background and initialize per-agent context
        activity_background = schd.format_activity_background()
        # participants order is deterministic: [proposer] + sorted(other_yes_responders)
        # built in scheduling.py:confirm_schedule(), preserved through JSONL serialization
        participants = list(schd.participants)

        if logger:
            logger.info(
                f"[VERIFY-JOINT] ========== Starting joint activity at {self.time} =========="
            )
            logger.info(
                f"[VERIFY-JOINT] Activity: {self.activity_name}, Location: {schd.location}"
            )
            logger.info(f"[VERIFY-JOINT] Participants: {participants}")
            logger.info(f"[VERIFY-JOINT] Proposer: {schd.proposer}")

        # Record initial states for comparison
        states_before = {}
        if logger:
            for agent in self.agents:
                state = agent.dm.read_state()
                states_before[agent.name] = {
                    "vitality": state["vitality"],
                    "fulfillment": state["fulfillment"].copy(),
                    "skills": state.get("skills", {}).copy(),
                    "possessions_count": len(state["assets"]["possessions"]),
                }
                logger.info(
                    f"[VERIFY-JOINT-STATE] {agent.name} before: vitality={state['vitality']}, "
                    f"fulfillment={state['fulfillment']}, "
                    f"possessions={len(state['assets']['possessions'])}"
                )

        # Initialize in-memory possessions for all agents
        # This ensures gift operations see the latest possessions without exclude_cur_t issues
        agent_possessions: Dict[str, List[Dict]] = {}
        for agent in self.agents:
            state = agent.dm.read_state()
            agent_possessions[agent.name] = state["assets"]["possessions"].copy()

        # Scratchpad creation is handled inside enter_joint_activity() via meet_person().
        # Participants' public info is injected inside DataManager.activity_prompt.

        for agent in self.agents:
            agent.enter_joint_activity(
                activity_background=activity_background,
                activity_type="joint",
                participants=participants,
                location_desc=location_desc,
            )

        from src.agents.prompts import (
            GOD_PROMPT_JOINT_ACTIVITY,
            GOD_PROMPT_JOINT_ACTIVITY_WITH_VERIFICATION,
            get_world_setting,
        )

        enable_verification = get_world_config()["activity"]["enable_verification"]
        prompt_template = (
            GOD_PROMPT_JOINT_ACTIVITY_WITH_VERIFICATION
            if enable_verification
            else GOD_PROMPT_JOINT_ACTIVITY
        )
        world_name = get_world_config()["name"]
        god_model_prompt = prompt_template.format(
            activity_background=activity_background,
            participants=participants,
            min_turns=min_turns,
            max_turns=max_turns,
            world_setting=get_world_setting(world_name),
        )
        god_model_messages = [{"role": "system", "content": god_model_prompt}]

        i_turn = 1
        last_speaker = None
        # Track gift actions: (sender_name, receiver_name, item_name, item_description)
        gift_actions: List[Tuple[str, str, str, str]] = []
        # Maintain dialog history in real-time
        dialog_history_lines: List[str] = []
        # Track active participants (those who haven't exited)
        active_participants: List[str] = list(participants)

        while i_turn <= max_turns:
            # Build active agents list once per iteration
            active_agents = [ag for ag in self.agents if ag.name in active_participants]

            god_response, env_fdbk, speaker, verification = env_and_nsp(
                god_model_messages,
                active_participants,
                last_speaker=last_speaker,
                allow_end=(i_turn >= min_turns),
            )

            # Mark last speaker's generation as rejected if verification fails
            if last_speaker and verification.lower().startswith("reject"):
                last_speaker_ag = next(a for a in self.agents if a.name == last_speaker)
                last_speaker_ag.mark_last_generation_rejected(verification)
                if logger:
                    logger.info(f"[VERIFY-REJECT] {last_speaker}: {verification}")

            god_model_messages.append({"role": "assistant", "content": god_response})
            # Update dialog history in real-time
            dialog_history_lines.append(f"Environment: {god_response}")

            for ag in active_agents:
                # RoleAgent.receive_in_activity only takes plain content
                ag.receive_in_activity(f"Environment: {env_fdbk}")

            # Decide next speaker

            if (speaker == END_SIGN and i_turn >= min_turns) or i_turn >= max_turns:
                break

            speaker_ag = next(a for a in self.agents if a.name == speaker)

            resp = speaker_ag.act_in_activity(i_turn=i_turn)

            # Record response first (including farewell message if exiting)
            god_model_messages.append({"role": "user", "content": resp})
            dialog_history_lines.append(resp)

            # Parse gift actions from response
            parsed_gifts, parse_errs = self._parse_gift_actions(resp, speaker)
            if parse_errs:
                # Feedback parse errors to agent
                err_msg = "Parse errors in your gift actions:\n" + "\n".join(
                    f"- {act}: {err}" for act, err in parse_errs.items()
                )
                speaker_ag.receive_in_activity(err_msg)

            # Execute gift actions immediately
            agent_by_name = {ag.name: ag for ag in self.agents}
            for sender_name, receiver_name, item_name in parsed_gifts:
                success, notif_sender, notif_receiver, item_description = (
                    self._exec_gift(
                        sender_name, receiver_name, item_name, agent_possessions
                    )
                )

                if success:
                    # Send system notifications to both agents
                    agent_by_name[sender_name].receive_in_activity(notif_sender)
                    agent_by_name[receiver_name].receive_in_activity(notif_receiver)
                    # Record successful gift for outcome tracking (include description)
                    gift_actions.append(
                        (sender_name, receiver_name, item_name, item_description)
                    )
                    if logger:
                        logger.info(
                            f"[VERIFY-JOINT-GIFTS] Gift executed: {sender_name} → {receiver_name}: {item_name}"
                        )
                else:
                    # Send error notification to sender
                    agent_by_name[sender_name].receive_in_activity(notif_sender)
                    if logger:
                        logger.warning(
                            f"[VERIFY-JOINT-GIFTS] Gift failed: {sender_name} → {receiver_name}: {item_name} - {notif_sender}"
                        )

            # Check for exit action (after recording response)
            if self._parse_exit_action(resp):
                active_participants.remove(speaker)
                exit_notice = f"({speaker} has left the activity)"
                # Broadcast exit notice to remaining active participants
                for ag in active_agents:
                    if ag.name != speaker:
                        ag.receive_in_activity(exit_notice)
                # Record exit notice in god_model history
                god_model_messages.append({"role": "user", "content": exit_notice})
                dialog_history_lines.append(exit_notice)
                if logger:
                    logger.info(
                        f"[VERIFY-JOINT-EXIT] {speaker} exited activity. "
                        f"Remaining: {active_participants}"
                    )
                # Check if not enough participants
                if len(active_participants) < 2:
                    if logger:
                        logger.info(
                            f"[VERIFY-JOINT-EXIT] Activity ending early: "
                            f"only {len(active_participants)} participant(s) left"
                        )
                    break
                last_speaker = speaker
                i_turn += 1
                continue

            # Broadcast with visibility control (only to active participants, excluding speaker)
            other_active_agents = [ag for ag in active_agents if ag.name != speaker]
            visible_content_by_person = {ag: "" for ag in other_active_agents}
            for blk_type, blk, visible_group in split_response_by_visible_blocks(resp):
                blk = blk.strip()
                if not blk:
                    continue

                if blk_type == "private":
                    continue
                elif blk_type == "public":
                    for other in other_active_agents:
                        visible_content_by_person[other] += blk
                elif blk_type == "group":
                    for other in other_active_agents:
                        assert visible_group is not None and len(visible_group) > 0
                        if other.name in visible_group:
                            visible_content_by_person[other] += blk
                        else:
                            visible_content_by_person[other] += (
                                f"\n\n({speaker} is discreetly interacting with {', '.join(visible_group)}, "
                                "but you don't know what they are exactly doing)\n\n"
                            )

            # Sorted by agent name for cache determinism
            for other, content in sorted(
                visible_content_by_person.items(), key=lambda x: x[0].name
            ):
                other.receive_in_activity(content)

            last_speaker = speaker
            i_turn += 1

        # ========== BUILD GIFTS FOR OUTCOME: build outcome data from executed gift_actions ==========
        gifts_by_agent: Dict[str, List[Dict]] = {}

        for sender_name, receiver_name, item_name, item_description in gift_actions:
            # Initialize gift lists if needed
            if sender_name not in gifts_by_agent:
                gifts_by_agent[sender_name] = []
            if receiver_name not in gifts_by_agent:
                gifts_by_agent[receiver_name] = []

            # Sender's record: item sent
            gifts_by_agent[sender_name].append(
                {
                    "name": item_name,
                    "description": item_description,
                    "to": receiver_name,
                    "action": "sent",
                }
            )

            # Receiver's record: item received
            gifts_by_agent[receiver_name].append(
                {
                    "name": item_name,
                    "description": item_description,
                    "from": sender_name,
                    "action": "received",
                }
            )

        if logger:
            logger.info(
                f"[VERIFY-JOINT-GIFTS] Recording {sum(len(g) for g in gifts_by_agent.values())} gift transactions for outcome"
            )
            for agent_name, gifts in gifts_by_agent.items():
                for gift in gifts:
                    action = gift["action"]
                    if action == "sent":
                        logger.info(
                            f"[VERIFY-JOINT-GIFTS] {agent_name} → {gift['to']}: {gift['name']}"
                        )
                    else:
                        logger.info(
                            f"[VERIFY-JOINT-GIFTS] {agent_name} ← {gift['from']}: {gift['name']}"
                        )

        # ========== EVALUATE: GodModel evaluates state changes for all participants ==========
        from src.world.god import evaluate_joint_activity
        from src.world.joint_activity_data import JointActivityRecord

        # Use real-time maintained dialog history
        dialog_history = "\n\n".join(dialog_history_lines)

        if logger:
            logger.info(
                f"[VERIFY-JOINT-STEP1] ========== EVALUATE: GodModel evaluates all participants =========="
            )
            logger.info(
                f"[VERIFY-JOINT-STEP1] Dialog turns: {len(dialog_history_lines)}"
            )

        # Evaluate all participants
        outcomes = evaluate_joint_activity(
            agents=self.agents,
            activity_background=activity_background,
            dialog_history=dialog_history,
        )

        # Add gift information to outcomes
        for agent_name, gifts in gifts_by_agent.items():
            if agent_name not in outcomes:
                if logger:
                    logger.error(
                        f"[VERIFY-JOINT-GIFTS] Agent {agent_name} not in outcomes! This should not happen."
                    )
                continue

            for gift in gifts:
                if gift["action"] == "sent":
                    outcomes[agent_name].items_sent.append(gift)
                elif gift["action"] == "received":
                    outcomes[agent_name].items_received.append(gift)

        if logger:
            logger.info(
                f"[VERIFY-JOINT-STEP1] Evaluation completed, {len(outcomes)} outcomes generated"
            )
            for agent_name, outcome in outcomes.items():
                logger.info(
                    f"[VERIFY-JOINT-STEP1] {agent_name}: "
                    f"delta_vitality={outcome.delta_vitality}, "
                    f"delta_fulfillment={outcome.delta_fulfillment}, "
                    f"delta_skills={outcome.delta_skills}, "
                    f"items_sent={outcome.items_sent}, "
                    f"items_received={outcome.items_received}"
                )

        # ========== RECEIVE: each agent receives its outcome (aligned with Solo) ==========
        if logger:
            logger.info(
                f"[VERIFY-JOINT-STEP2] ========== RECEIVE: each agent receives outcome =========="
            )

        for agent in self.agents:
            outcome = outcomes[agent.name]
            # Format outcome message for agent (similar to Solo)
            outcome_message = self._format_outcome_message(outcome)
            agent.receive_in_activity(outcome_message)

            if logger:
                logger.info(
                    f"[VERIFY-JOINT-STEP2] {agent.name} received outcome message"
                )

        # ========== EXIT: generate summary (aligned with Solo) ==========
        if logger:
            logger.info(f"[VERIFY-JOINT-STEP3] ========== EXIT: generate summary ==========")

        summaries_and_reflections = {}
        for agent in self.agents:
            # Call exit_activity (outcome already received in RECEIVE step)
            summary, reflection = agent.exit_activity(activity_type="joint")
            summaries_and_reflections[agent.name] = (summary, reflection)

            if logger:
                save_feature_generation(
                    messages=[
                        {
                            "role": "user",
                            "content": f"Agent {agent.name} exit joint activity",
                        }
                    ],
                    output=f"Summary: {summary}\n\nReflection: {reflection}",
                    feature="joint_activity",
                    extra={"agent": agent.name, "stage": "exit_joint"},
                )
                logger.info(
                    f"[VERIFY-JOINT-STEP3] {agent.name} summary length: {len(summary)}"
                )
                logger.info(
                    f"[VERIFY-JOINT-STEP3] {agent.name} reflection length: {len(reflection)}"
                )

        # ========== APPLY: apply state changes (aligned with Solo) ==========
        if logger:
            logger.info(
                f"[VERIFY-JOINT-STEP4] ========== APPLY: apply state changes =========="
            )

        # Apply all changes (possessions + vitality/fulfillment/skills) in a single write
        states_after = {}
        for agent in self.agents:
            outcome = outcomes[agent.name]
            state_after = agent.dm.apply_activity_outcome(
                outcome, possessions=agent_possessions[agent.name]
            )
            states_after[agent.name] = state_after

            if logger:
                logger.info(
                    f"[VERIFY-JOINT-STEP4] Applied all changes for {agent.name} "
                    f"(possessions={len(agent_possessions[agent.name])}, "
                    f"vitality_delta={outcome.delta_vitality})"
                )

        # Verify state changes
        if logger:
            logger.info(
                f"[VERIFY-JOINT-STEP5] ========== CONSISTENCY: verify state changes =========="
            )
            for agent in self.agents:
                state_after = states_after[agent.name]
                state_before = states_before[agent.name]
                outcome = outcomes[agent.name]

                actual_vitality_delta = (
                    state_after["vitality"] - state_before["vitality"]
                )
                expected_vitality_delta = outcome.delta_vitality

                if actual_vitality_delta != expected_vitality_delta:
                    logger.warning(
                        f"[VERIFY-JOINT-STEP5] {agent.name} vitality delta mismatch! "
                        f"Expected {expected_vitality_delta}, got {actual_vitality_delta}"
                    )
                else:
                    logger.info(
                        f"[VERIFY-JOINT-STEP5] {agent.name} vitality delta verified: {actual_vitality_delta}"
                    )

                # Check fulfillment deltas
                for key in ["mood", "social", "esteem"]:
                    if key in outcome.delta_fulfillment:
                        actual_delta = (
                            state_after["fulfillment"][key]
                            - state_before["fulfillment"][key]
                        )
                        expected_delta = outcome.delta_fulfillment[key]
                        if actual_delta != expected_delta:
                            logger.warning(
                                f"[VERIFY-JOINT-STEP5] {agent.name} {key} delta mismatch! "
                                f"Expected {expected_delta}, got {actual_delta}"
                            )
                        else:
                            logger.info(
                                f"[VERIFY-JOINT-STEP5] {agent.name} {key} delta verified: {actual_delta}"
                            )

        # ========== RECORD: save records (aligned with Solo) ==========
        if logger:
            logger.info(f"[VERIFY-JOINT-STEP6] ========== RECORD: save records ==========")

        for agent in self.agents:
            outcome = outcomes[agent.name]
            summary, reflection = summaries_and_reflections[agent.name]

            # Create and save joint activity record
            record = JointActivityRecord(
                agent_name=agent.name,
                time=self.time,
                activity_id=self.activity_id,
                activity_name=self.activity_name,
                summary=summary,
                reflection=reflection,
                participants=schd.participants,
                location=schd.location,
                outcome=outcome,
            )
            agent.dm.append_joint_activity_record(record)

            if logger:
                logger.info(f"[VERIFY-JOINT-STEP6] Saved record for {agent.name}")

        if logger:
            logger.info(
                f"[VERIFY-JOINT] ========== Joint activity completed for all {len(self.agents)} participants =========="
            )


@dataclass
class SoloActivity(Activity):
    """Single-person activity with unified data-driven design."""

    def __post_init__(self) -> None:
        """Auto-generate activity_id if not provided."""
        if self.activity_id is None:
            if not self.agents:
                raise ValueError("SoloActivity requires at least 1 agent")
            self.activity_id = make_activity_id("solo", self.time, self.agents[0].name)

    def run(self) -> None:
        """Execute solo activity with two-stage evaluation: type eval -> (optional) offer generation -> apply -> record."""
        from src.world.solo_activity_data import ActionOutcome, SoloActivityRecord
        from src.utils import get_verify_logger

        # VERIFY_FEATURE: solo_activity
        logger = get_verify_logger(feature="solo_activity")
        agent = self.agents[0]

        if logger:
            logger.info(
                f"[VERIFY-SOLO] ========== Starting solo activity for {agent.name} at {self.time} =========="
            )

        # Record initial state for comparison
        state_before = None
        if logger:
            state_before = agent.dm.read_state()
            logger.info(
                f"[VERIFY-SOLO-STATE] State before: vitality={state_before['vitality']}, "
                f"fulfillment={state_before['fulfillment']}, "
                f"deposit={state_before['assets']['deposit']}, "
                f"possessions_count={len(state_before['assets']['possessions'])}"
            )
            logger.info(
                f"[VERIFY-SOLO-STATE] Skills before: {state_before.get('skills', {})}"
            )

        # Step 1: Agent enters solo activity (builds activity_context only)
        agent.enter_solo_activity()
        if logger:
            logger.info(
                f"[VERIFY-SOLO-STEP1] Agent entered solo activity, context built"
            )

        # Step 2: Agent acts (generates action/analysis)
        action = agent.act_in_activity(activity_type="solo")
        # Save agent's LLM output for verification
        from src.utils import save_feature_generation

        save_feature_generation(
            messages=[
                {
                    "role": "user",
                    "content": f"Agent {agent.name} activity context (last message)",
                }
            ],
            output=action,
            feature="solo_activity",
            extra={"agent": agent.name, "stage": "agent_act"},
        )

        if logger:
            logger.info(
                f"[VERIFY-SOLO-STEP2] Agent generated action (length={len(action)})"
            )
            logger.info(f"[VERIFY-SOLO-STEP2] Action preview: {action[:200]}...")
            logger.info(
                f"[VERIFY-SOLO-STEP2] Full LLM output saved to generations/ directory"
            )

        # Extract activity content from the full response (remove "Thinking:" section)
        from src.agents.response_validator import extract_activity_content

        activity_content = extract_activity_content(action)
        if logger:
            logger.info(
                f"[VERIFY-SOLO-STEP2] Extracted activity content (length={len(activity_content)})"
            )
            logger.info(
                f"[VERIFY-SOLO-STEP2] Content preview: {activity_content[:200]}..."
            )

        # Step 3: Stage 1 - GodModel evaluates activity
        outcome_text_or_none, is_consumption, deltas_or_none = (
            self._evaluate_solo_activity(agent, activity_content)
        )

        # AGENTOPIA_V17451_HF2_SOLO_NONE_FAIL_FORWARD
        # A failed God-model evaluation must never terminate the world.
        # Convert an empty non-consumption evaluation into a deterministic
        # no-op outcome so downstream logging and ActionOutcome construction
        # always receive valid types.
        if not is_consumption:
            if not isinstance(outcome_text_or_none, str) or not outcome_text_or_none.strip():
                if logger:
                    logger.warning(
                        "[VERIFY-SOLO-STEP3][FAIL-FORWARD] "
                        "No valid outcome text returned; applying zero-impact outcome"
                    )
                outcome_text_or_none = (
                    "The activity ends without a clear measurable change."
                )

            if not isinstance(deltas_or_none, dict):
                if logger:
                    logger.warning(
                        "[VERIFY-SOLO-STEP3][FAIL-FORWARD] "
                        "No valid delta mapping returned; applying zero deltas"
                    )
                deltas_or_none = {}

            deltas_or_none = dict(deltas_or_none)

            if not isinstance(deltas_or_none.get("delta_vitality"), (int, float)):
                deltas_or_none["delta_vitality"] = 0
            if not isinstance(deltas_or_none.get("delta_fulfillment"), dict):
                deltas_or_none["delta_fulfillment"] = {}
            if not isinstance(deltas_or_none.get("delta_skills"), dict):
                deltas_or_none["delta_skills"] = {}
            if not isinstance(deltas_or_none.get("delta_money"), (int, float)):
                deltas_or_none["delta_money"] = 0
            if not isinstance(deltas_or_none.get("gain_items"), list):
                deltas_or_none["gain_items"] = []

        if logger:
            logger.info(f"[VERIFY-SOLO-STEP3] Stage 1 evaluation completed")
            logger.info(f"[VERIFY-SOLO-STEP3] Is consumption event: {is_consumption}")
            if is_consumption:
                logger.info(
                    f"[VERIFY-SOLO-STEP3] Consumption event detected, deferring outcome to Stage 2"
                )
            else:
                logger.info(
                    f"[VERIFY-SOLO-STEP3] Outcome text: {outcome_text_or_none[:200]}..."
                )
                logger.info(
                    f"[VERIFY-SOLO-STEP3] Non-consumption deltas: vitality={deltas_or_none.get('delta_vitality')}, "
                    f"fulfillment={deltas_or_none.get('delta_fulfillment')}, "
                    f"skills={deltas_or_none.get('delta_skills')}, "
                    f"money={deltas_or_none.get('delta_money')}, "
                    f"items={deltas_or_none.get('gain_items')}"
                )

        # Step 4: For non-consumption, agent receives outcome from environment
        if not is_consumption:
            agent.receive_in_activity(f"Outcome: {outcome_text_or_none}")
            if logger:
                logger.info(
                    f"[VERIFY-SOLO-STEP4] Agent received outcome from environment"
                )

        # Initialize tracking variables
        consumption_purchased = None
        consumption_options_offered = []
        purchase_response = ""

        if is_consumption:
            # Step 5a: Stage 2 - Generate consumption scenario and offers
            outcome_text, consumption_options_offered = (
                self._generate_consumption_offers(agent, activity_content)
            )
            if logger:
                logger.info(
                    f"[VERIFY-SOLO-STEP5-CONSUMPTION] Stage 2: Generated outcome and {len(consumption_options_offered)} consumption options"
                )
                logger.info(
                    f"[VERIFY-SOLO-STEP5-CONSUMPTION] Outcome: {outcome_text[:200]}..."
                )
                for idx, opt in enumerate(consumption_options_offered):
                    logger.info(
                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] Option {idx + 1}: {opt.name} - ${opt.price} - {opt.description}"
                    )

            # Initialize default deltas for consumption (no purchase)
            delta_vitality = 0
            delta_fulfillment = {"material": 0}
            delta_skills = {}
            delta_money = 0
            gain_items = []

            # Check if options are available
            if len(consumption_options_offered) == 0:
                # Items don't fit worldview - inform agent and skip purchase flow
                no_items_message = f"""
## Observation
{outcome_text}

Unfortunately, you cannot purchase anything here. The items you're looking for are not available.
"""
                agent.receive_in_activity(no_items_message.strip())
                if logger:
                    logger.info(
                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] No consumption options available (items don't fit worldview)"
                    )
                    logger.info(
                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] Skipping purchase flow, using default deltas"
                    )
            else:
                # Normal purchase flow: present options and let agent choose
                # Get current deposit to check affordability
                current_deposit = agent.dm.read_state()["assets"]["deposit"]
                if logger:
                    logger.info(
                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] Current deposit: ${current_deposit}"
                    )

                # Build combined prompt with outcome and consumption options
                options_name = [opt.name for opt in consumption_options_offered]
                options_text = "\n".join(
                    [
                        f"  - {opt.name}: ${opt.price} - {opt.description}"
                        for opt in consumption_options_offered
                    ]
                )
                consumption_prompt = f"""
## Observation

{outcome_text}

## You have the following consumption options available:

{options_text}

Your current deposit: ${current_deposit}

You can purchase at most ONE item. If you cannot afford an item or don't want to purchase anything, you can choose not to buy.

Consider your current financial situation, needs, priorities, and values.

First, express your thoughts and ideas.
Then, output your decision using the <buy> tag.

Format:
[Your thoughts and considerations...]

<buy>Item Name</buy>
(You should use the exact item name as listed in {options_name}.)

Or if you don't want to purchase anything:
<buy>None</buy>
"""
                agent.receive_in_activity(consumption_prompt.strip())
                if logger:
                    logger.info(
                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] Sent outcome and consumption options to agent"
                    )

                # Agent decides what to purchase
                purchase_response = agent.act_in_activity(activity_type="solo")

                # Save agent's purchase decision LLM output
                save_feature_generation(
                    messages=[
                        {
                            "role": "user",
                            "content": f"Agent {agent.name} purchase decision prompt",
                        }
                    ],
                    output=purchase_response,
                    feature="solo_activity",
                    extra={"agent": agent.name, "stage": "agent_purchase_decision"},
                )

                # Extract content from <buy> tag
                import re

                buy_match = re.search(
                    r"<buy>(.*?)</buy>", purchase_response, re.IGNORECASE | re.DOTALL
                )
                if buy_match:
                    selected_name = buy_match.group(1).strip()
                else:
                    # Fallback: use full response if no tag found
                    selected_name = purchase_response.strip()

                if logger:
                    logger.info(
                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] Agent purchase decision: '{selected_name}'"
                    )
                    logger.info(
                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] Full LLM output saved to generations/ directory"
                    )

                # Validate and process purchase
                if selected_name.upper() == "NONE":
                    # No purchase
                    if logger:
                        logger.info(
                            f"[VERIFY-SOLO-STEP5-CONSUMPTION] Agent chose not to purchase anything (NONE)"
                        )
                else:
                    # Match selected option with three-stage matching (strict → contains → fuzzy)
                    selected_opt = None

                    # Stage 1: Strict match (exact name)
                    for opt in consumption_options_offered:
                        if opt.name == selected_name:
                            selected_opt = opt
                            if logger:
                                logger.info(
                                    f"[VERIFY-SOLO-STEP5-CONSUMPTION] Strict match: '{selected_name}'"
                                )
                            break

                    # Stage 2: Contains match
                    if selected_opt is None:
                        for opt in consumption_options_offered:
                            if opt.name in selected_name:
                                selected_opt = opt
                                if logger:
                                    logger.info(
                                        f"[VERIFY-SOLO-STEP5-CONSUMPTION] Contains match: '{opt.name}' found in '{selected_name}'"
                                    )
                                break

                    # Stage 3: Fuzzy match
                    if selected_opt is None:
                        import difflib

                        option_names = [opt.name for opt in consumption_options_offered]
                        closest = difflib.get_close_matches(
                            selected_name, option_names, n=1, cutoff=0.7
                        )
                        if closest:
                            selected_opt = next(
                                opt
                                for opt in consumption_options_offered
                                if opt.name == closest[0]
                            )
                            if logger:
                                logger.info(
                                    f"[VERIFY-SOLO-STEP5-CONSUMPTION] Fuzzy match: '{selected_name}' → '{selected_opt.name}'"
                                )

                    if selected_opt is None:
                        # Invalid selection - treat as no purchase
                        if logger:
                            logger.warning(
                                f"[VERIFY-SOLO-STEP5-CONSUMPTION] Invalid selection '{selected_name}', treating as no purchase"
                            )
                            logger.info(
                                f"[VERIFY-SOLO-STEP5-CONSUMPTION] Available options: {[opt.name for opt in consumption_options_offered]}"
                            )
                    elif selected_opt.price > current_deposit:
                        # Cannot afford - treat as no purchase
                        if logger:
                            logger.warning(
                                f"[VERIFY-SOLO-STEP5-CONSUMPTION] Cannot afford '{selected_opt.name}' (${selected_opt.price} > ${current_deposit}), no purchase"
                            )
                    else:
                        # Valid purchase
                        consumption_purchased = selected_opt.name
                        delta_money = -selected_opt.price
                        gain_items = [
                            {
                                "name": selected_opt.name,
                                "description": selected_opt.description,
                                "purchase_price": selected_opt.price,
                            }
                        ]

                        # Calculate Material fulfillment based on spending amount
                        from src.utils import calculate_material_from_cost

                        delta_material = calculate_material_from_cost(
                            selected_opt.price
                        )

                        # Apply config limits
                        from src.config import get_config

                        config = get_config()
                        material_limit = config["world"]["solo_activity"][
                            "delta_limits"
                        ]["fulfillment"]["material"]["max"]
                        delta_fulfillment["material"] = min(
                            material_limit, delta_material
                        )

                        if logger:
                            logger.info(
                                f"[VERIFY-SOLO-STEP5-CONSUMPTION] Valid purchase: '{selected_opt.name}' for ${selected_opt.price}"
                            )
                            logger.info(
                                f"[VERIFY-SOLO-STEP5-CONSUMPTION] Material fulfillment: raw_calculation={delta_material}, limit={material_limit}, final={delta_fulfillment['material']}"
                            )
                            logger.info(
                                f"[VERIFY-SOLO-STEP5-CONSUMPTION] Deltas: money=-{selected_opt.price}, material=+{delta_fulfillment['material']}, gain_items={gain_items}"
                            )

                        # Send purchase confirmation message to agent
                        remaining_deposit = current_deposit - selected_opt.price
                        purchase_confirmation = f"""
Purchase completed:
- Spent: ${selected_opt.price}
- Purchased: {selected_opt.name}
- Remaining deposit: ${remaining_deposit}
- New possession: {selected_opt.name}
"""
                        agent.receive_in_activity(purchase_confirmation.strip())
                        if logger:
                            logger.info(
                                f"[VERIFY-SOLO-STEP5-CONSUMPTION] Sent purchase confirmation to agent"
                            )

            # Create ActionOutcome for consumption
            outcome = ActionOutcome(
                outcome=outcome_text,
                is_consumption_event=True,
                delta_vitality=delta_vitality,
                delta_fulfillment=delta_fulfillment,
                delta_skills=delta_skills,
                delta_money=delta_money,
                gain_items=gain_items,
            )
        else:
            # Step 5b: Use deltas from Stage 1 (non-consumption)
            if logger:
                logger.info(
                    f"[VERIFY-SOLO-STEP5-NON_CONSUMPTION] Using deltas from Stage 1 (non-consumption path)"
                )
                logger.info(
                    f"[VERIFY-SOLO-STEP5-NON_CONSUMPTION] Deltas: vitality={deltas_or_none['delta_vitality']}, "
                    f"fulfillment={deltas_or_none['delta_fulfillment']}, "
                    f"skills={deltas_or_none['delta_skills']}, "
                    f"money={deltas_or_none['delta_money']}, "
                    f"items={deltas_or_none['gain_items']}"
                )

            # Create ActionOutcome for non-consumption
            outcome = ActionOutcome(
                outcome=outcome_text_or_none,
                is_consumption_event=False,
                delta_vitality=deltas_or_none["delta_vitality"],
                delta_fulfillment=deltas_or_none["delta_fulfillment"],
                delta_skills=deltas_or_none["delta_skills"],
                delta_money=deltas_or_none["delta_money"],
                gain_items=deltas_or_none["gain_items"],
            )

        # Step 5c: RECEIVE - Agent receives outcome deltas (aligned with Joint)
        outcome_message = self._format_outcome_message(outcome)
        agent.receive_in_activity(outcome_message)
        if logger:
            logger.info(f"[VERIFY-SOLO-STEP5C] Agent received outcome deltas")

        # Step 6: EXIT - Agent exits activity and generates reflection
        _, reflection = agent.exit_activity(activity_type="solo")

        # Save agent's reflection LLM output
        save_feature_generation(
            messages=[
                {"role": "user", "content": f"Agent {agent.name} exit activity prompt"}
            ],
            output=reflection,
            feature="solo_activity",
            extra={"agent": agent.name, "stage": "agent_exit_reflection"},
        )

        if logger:
            logger.info(f"[VERIFY-SOLO-STEP6] Agent exited activity (with deltas)")
            logger.info(
                f"[VERIFY-SOLO-STEP6] Reflexion length: {len(reflection)} chars"
            )
            logger.info(
                f"[VERIFY-SOLO-STEP6] Full LLM output saved to generations/ directory"
            )

        # Step 7: Apply deltas to state/skills/deposit/possessions
        state_after = agent.dm.apply_activity_outcome(outcome)
        if logger:
            logger.info(f"[VERIFY-SOLO-STEP7] Applied deltas to state")
            logger.info(
                f"[VERIFY-SOLO-STEP7-STATE] State after: vitality={state_after['vitality']}, "
                f"fulfillment={state_after['fulfillment']}, "
                f"deposit={state_after['assets']['deposit']}, "
                f"possessions_count={len(state_after['assets']['possessions'])}"
            )
            logger.info(
                f"[VERIFY-SOLO-STEP7-STATE] Skills after: {state_after.get('skills', {})}"
            )

            # Verify delta application consistency (considering clipping due to limits)
            if state_before:
                actual_vitality_delta = (
                    state_after["vitality"] - state_before["vitality"]
                )
                expected_vitality_delta = outcome.delta_vitality
                # Vitality has limits [0, 100], so delta may be clipped
                if actual_vitality_delta != expected_vitality_delta:
                    # Check if difference is due to clipping
                    if (
                        state_before["vitality"] + expected_vitality_delta > 100
                        and state_after["vitality"] == 100
                    ) or (
                        state_before["vitality"] + expected_vitality_delta < 0
                        and state_after["vitality"] == 0
                    ):
                        logger.info(
                            f"[VERIFY-SOLO-STEP7-CONSISTENCY] Vitality delta clipped by limits: expected {expected_vitality_delta}, got {actual_vitality_delta} (before: {state_before['vitality']}, after: {state_after['vitality']})"
                        )
                    else:
                        logger.warning(
                            f"[VERIFY-SOLO-STEP7-CONSISTENCY] Vitality delta mismatch! Expected {expected_vitality_delta}, got {actual_vitality_delta}"
                        )
                else:
                    logger.info(
                        f"[VERIFY-SOLO-STEP7-CONSISTENCY] Vitality delta verified: {actual_vitality_delta}"
                    )

                actual_deposit_delta = (
                    state_after["assets"]["deposit"] - state_before["assets"]["deposit"]
                )
                expected_deposit_delta = outcome.delta_money
                if actual_deposit_delta != expected_deposit_delta:
                    logger.warning(
                        f"[VERIFY-SOLO-STEP7-CONSISTENCY] Deposit delta mismatch! Expected {expected_deposit_delta}, got {actual_deposit_delta}"
                    )
                else:
                    logger.info(
                        f"[VERIFY-SOLO-STEP7-CONSISTENCY] Deposit delta verified: {actual_deposit_delta}"
                    )

        # Step 8: Record activity
        record = SoloActivityRecord(
            agent_name=agent.name,
            time=self.time,
            content=activity_content,
            outcome=outcome,
            reflection=reflection,
            consumption_options_offered=consumption_options_offered,
            consumption_purchased=consumption_purchased,
            purchase_response=purchase_response,
        )
        agent.dm.append_activity_record(record)
        if logger:
            logger.info(f"[VERIFY-SOLO-STEP8] Saved activity record for {agent.name}")
            logger.info(
                f"[VERIFY-SOLO] ========== Solo activity completed for {agent.name} =========="
            )

    def _evaluate_solo_activity(
        self, agent: "RoleAgent", activity_content: str
    ) -> tuple[str | None, bool, dict | None]:
        """Stage 1: GodModel evaluates solo activity.

        Returns:
            Tuple of (outcome_text_or_none, is_consumption_event, deltas_or_none)
            - Consumption: (None, True, None)
            - Non-consumption: (outcome, False, deltas)
        """
        from src.world.god import evaluate_solo_activity

        return evaluate_solo_activity(agent=agent, activity_content=activity_content)

    def _generate_consumption_offers(
        self, agent: "RoleAgent", activity_content: str
    ) -> tuple[str, list]:
        """Stage 2: GodModel generates consumption scenario and offers.

        Returns:
            Tuple of (outcome_text, consumption_options)
        """
        from src.world.god import generate_consumption_offers

        return generate_consumption_offers(
            agent=agent, activity_content=activity_content
        )


@dataclass
class PublicActivity(Activity):
    """Public activity (group event like interest class).

    Participants execute in parallel (like Solo) with no direct conversation.
    At EXIT stage, agents can optionally create scratchpads for people they want to remember.
    """

    schedule: Schedule
    event_description: str = ""

    @classmethod
    def from_schedule(
        cls,
        schd: Schedule,
        agents: List[RoleAgent],
        event_description: str = "",
    ) -> "PublicActivity":
        """Construct PublicActivity from Schedule."""
        return cls(
            activity_id=schd.activity_id,
            activity_name=schd.activity_name,
            time=schd.activity_time,
            agents=agents,
            schedule=schd,
            event_description=event_description,
        )

    def run(self, parallel: bool = True) -> None:
        """Execute public activity with standard flow (aligned with Solo).

        Public activities are group activities without direct conversation.
        Agents execute in parallel since they don't interact during the activity.

        Args:
            parallel: Whether to run agent tasks in parallel.

        Flow:
        1. ENTER: Each agent enters public activity context (parallel)
        2. ACT: Each agent participates independently (parallel)
        3. EVALUATE: GodModel evaluates outcomes for all participants (single call)
        4. RECEIVE + APPLY: Each agent receives outcome and applies changes (parallel)
        5. EXIT: Each agent reflects and can update scratchpads (parallel)
        6. RECORD: Save activity to each agent's record (parallel)
        """
        from src.utils import get_verify_logger, save_feature_generation
        from src.world.god import evaluate_public_activity
        from src.world.public_activity_data import PublicActivityRecord

        logger = get_verify_logger(feature="public_activity")
        participant_names = [ag.name for ag in self.agents]
        n_agents = len(self.agents)

        # Read internal_parallelism from config (must be > 0)
        cfg = get_world_config()
        internal_parallelism = int(cfg["public_activity"]["internal_parallelism"])
        if internal_parallelism <= 0:
            logger.error(
                f"internal_parallelism must be > 0, got {internal_parallelism}, forcing to 5"
            )
            internal_parallelism = 5
        effective_parallelism = min(n_agents, internal_parallelism)

        if logger:
            logger.info(
                f"[VERIFY-PUBLIC-ACT] ========== Starting public activity at {self.time} =========="
            )
            logger.info(
                f"[VERIFY-PUBLIC-ACT] Activity: {self.activity_name}, "
                f"Participants: {participant_names}, parallel={parallel}, internal_parallelism={effective_parallelism}"
            )

        # ========== GROUP SPLITTING for large activities ==========
        # >30: 2 groups, >60: 3 groups, >90: 4 groups
        if n_agents > 90:
            n_groups = 4
        elif n_agents > 60:
            n_groups = 3
        elif n_agents > 30:
            n_groups = 2
        else:
            n_groups = 1

        # Assign agents to groups (round-robin for even distribution)
        name_to_group: dict[str, int] = {}
        group_members: dict[int, list[str]] = {i: [] for i in range(n_groups)}
        for idx, name in enumerate(participant_names):
            group_idx = idx % n_groups
            name_to_group[name] = group_idx
            group_members[group_idx].append(name)

        if logger and n_groups > 1:
            logger.info(
                f"[VERIFY-PUBLIC-ACT] Split into {n_groups} groups: "
                + ", ".join(
                    f"group {i}: {len(group_members[i])} agents"
                    for i in range(n_groups)
                )
            )

        # Build participants_pub_info for EXIT phase (public info, same for all agents)
        reader_dm = self.agents[0].dm
        participants_pub_info: dict[str, str] = {
            name: reader_dm.read_others_pub_info(name) for name in participant_names
        }

        # ========== STEP 1: ENTER (parallel) ==========
        if logger:
            logger.info("[VERIFY-PUBLIC-ACT-STEP1] ===== ENTER =====")

        def enter_task(agent: RoleAgent) -> None:
            agent_group = name_to_group[agent.name]
            visible_participants = group_members[agent_group]
            group_info = (
                f" (Group {agent_group + 1} of {n_groups})" if n_groups > 1 else ""
            )
            agent.enter_public_activity(
                activity_name=self.activity_name,
                event_description=self.event_description,
                participants=visible_participants,
                group_info=group_info,
            )

        if parallel and n_agents > 1:
            with ThreadPoolExecutor(max_workers=effective_parallelism) as ex:
                list(ex.map(enter_task, self.agents))
        else:
            for agent in self.agents:
                enter_task(agent)

        # ========== STEP 2: ACT (parallel, main LLM calls) ==========
        if logger:
            logger.info(
                "[VERIFY-PUBLIC-ACT-STEP2] ===== ACT (with function calling) ====="
            )

        participation_outputs: dict[str, str] = {}

        def act_task(agent: RoleAgent) -> tuple[str, str]:
            response = agent.act_in_activity(activity_type="public")
            if logger:
                logger.info(
                    f"[VERIFY-PUBLIC-ACT-STEP2] {agent.name} participated, "
                    f"response length: {len(response) if response else 0}"
                )
                save_feature_generation(
                    messages=agent.activity_context,
                    output=response,
                    feature="public_activity",
                    extra={"agent": agent.name, "stage": "act"},
                )
            return agent.name, response

        if parallel and n_agents > 1:
            with ThreadPoolExecutor(max_workers=effective_parallelism) as ex:
                results = list(ex.map(act_task, self.agents))
            for name, response in results:
                participation_outputs[name] = response
        else:
            for agent in self.agents:
                name, response = act_task(agent)
                participation_outputs[name] = response

        # ========== STEP 3: EVALUATE (single call, cannot parallel) ==========
        if logger:
            logger.info("[VERIFY-PUBLIC-ACT-STEP3] ===== EVALUATE =====")

        outcomes = evaluate_public_activity(
            agents=self.agents,
            activity_name=self.activity_name,
            event_description=self.event_description,
            participation_outputs=participation_outputs,
        )

        if logger:
            for agent_name, outcome in outcomes.items():
                logger.info(
                    f"[VERIFY-PUBLIC-ACT-STEP3] {agent_name}: "
                    f"delta_vitality={outcome.delta_vitality}, "
                    f"delta_fulfillment={outcome.delta_fulfillment}, "
                    f"delta_skills={outcome.delta_skills}"
                )

        # ========== STEP 4+5: RECEIVE + APPLY (parallel) ==========
        if logger:
            logger.info("[VERIFY-PUBLIC-ACT-STEP4+5] ===== RECEIVE + APPLY =====")

        def receive_apply_task(agent: RoleAgent) -> None:
            outcome = outcomes[agent.name]
            outcome_message = self._format_outcome_message(outcome)
            agent.receive_in_activity(outcome_message)
            agent.dm.apply_activity_outcome(outcome)
            if logger:
                logger.info(
                    f"[VERIFY-PUBLIC-ACT-STEP4+5] {agent.name} received + applied: "
                    f"vitality_delta={outcome.delta_vitality}"
                )

        if parallel and n_agents > 1:
            with ThreadPoolExecutor(max_workers=effective_parallelism) as ex:
                list(ex.map(receive_apply_task, self.agents))
        else:
            for agent in self.agents:
                receive_apply_task(agent)

        # ========== STEP 6: EXIT (parallel, LLM calls for reflection) ==========
        if logger:
            logger.info("[VERIFY-PUBLIC-ACT-STEP6] ===== EXIT =====")

        # Build all_participation for EXIT phase (per-group filtered)
        all_participation: dict[str, str] = {}
        for name in participant_names:
            pub_info = participants_pub_info[name]
            activity_desc = clip_str(participation_outputs[name], 300)
            all_participation[name] = (
                f"(Public info: {pub_info})\n  Participation: {activity_desc}"
            )

        reflections: dict[str, str] = {}

        def exit_task(agent: RoleAgent) -> tuple[str, str]:
            # Only pass group members' participation to this agent
            agent_group = name_to_group[agent.name]
            visible_names = group_members[agent_group]
            visible_participation = {n: all_participation[n] for n in visible_names}
            _, reflection = agent.exit_activity(
                activity_type="public",
                all_participation=visible_participation,
            )
            if logger:
                logger.info(
                    f"[VERIFY-PUBLIC-ACT-STEP6] {agent.name} EXIT, "
                    f"reflection length: {len(reflection)}"
                )
            return agent.name, reflection

        if parallel and n_agents > 1:
            with ThreadPoolExecutor(max_workers=effective_parallelism) as ex:
                results = list(ex.map(exit_task, self.agents))
            for name, reflection in results:
                reflections[name] = reflection
        else:
            for agent in self.agents:
                name, reflection = exit_task(agent)
                reflections[name] = reflection

        # ========== STEP 7: RECORD (parallel) ==========
        if logger:
            logger.info("[VERIFY-PUBLIC-ACT-STEP7] ===== RECORD =====")

        def record_task(agent: RoleAgent) -> None:
            outcome = outcomes[agent.name]
            record = PublicActivityRecord(
                agent_name=agent.name,
                time=self.time,
                activity_id=self.activity_id,
                activity_name=self.activity_name,
                event_description=self.event_description,
                participants=participant_names,
                participation=participation_outputs[agent.name],
                reflection=reflections[agent.name],
                outcome=outcome,
            )
            agent.dm.append_public_activity_record(record)
            if logger:
                logger.info(f"[VERIFY-PUBLIC-ACT-STEP7] Saved record for {agent.name}")

        if parallel and n_agents > 1:
            with ThreadPoolExecutor(max_workers=effective_parallelism) as ex:
                list(ex.map(record_task, self.agents))
        else:
            for agent in self.agents:
                record_task(agent)

        if logger:
            logger.info(
                f"[VERIFY-PUBLIC-ACT] ========== Public activity completed =========="
            )
