import re


class ConversationState:
    """
    Manages conversation state for UniAI V2:
    - chat_history: Recent conversational turns (user query, assistant response, records)
    - last_notice_records: The most recent list of notice documents returned to the student
    - active_notice: The specific notice document currently being discussed
    - active_notice_id: The exact MongoDB/Pinecone notice_id of the active notice
    - session_memory: Session-only memory for user preferences and corrections (e.g. student's name)
    """

    def __init__(self, history_window=5, max_turns_stored=25):
        # Bound the retained conversation. This state is process-local and
        # should not grow indefinitely for an active browser session.
        self.history_window = max(1, int(history_window))
        self.max_turns_stored = max(self.history_window, int(max_turns_stored))
        self.chat_history = []
        self.last_notice_records = []
        self.last_answer_records = []
        self.active_notice = None
        self.active_notice_id = None
        self.session_memory = {}

    def extract_and_remember_user_name(self, text):
        """Remember only *explicit* self-identification and name corrections.

        Never infer a name from generic statements such as "it's closed",
        "I am looking for notices", or a notice's contents.
        """
        message = str(text or "").strip()
        if not message:
            return self.session_memory.get("user_name")

        # Allow a name and optional family name, but do not extract entire
        # sentences. A name is stored only on a clear identity declaration.
        pattern = (
            r"\b(?:my\s+name\s+is|call\s+me|"
            r"correct\s+my\s+name\s+to|change\s+my\s+name\s+to)"
            r"\s+([A-Za-z]+(?:[ -](?!and\b|but\b|because\b|please\b|who\b|from\b|is\b)[A-Za-z]+)?)\b"
        )
        match = re.search(pattern, message, re.IGNORECASE)
        if not match:
            # Accept a short standalone "I'm Farhan" / "I am Farhan",
            # not "I am looking for the exam notices".
            match = re.fullmatch(
                r"(?:i\s+am|i['’]m)\s+([A-Za-z]+(?:[ -][A-Za-z]+)?)"
                r"[.!]?", message, re.IGNORECASE
            )
        if not match and self.session_memory.get("user_name"):
            # A concise correction is meaningful only after the session has
            # already established that it is discussing the student's name.
            match = re.fullmatch(
                r"(?:correct\s+it|correction)\s*[:,]\s*([A-Za-z]+(?:[ -][A-Za-z]+)?)\.?",
                message, re.IGNORECASE,
            )
        if not match:
            return self.session_memory.get("user_name")

        raw_name = match.group(1).strip()
        non_names = {
            "a", "the", "student", "uniai", "here", "just", "looking",
            "trying", "fine", "okay", "ok", "interested", "studying",
            "going", "not", "ready", "asking", "confused", "happy",
            "sorry", "learning", "checking", "from", "searching",
            "when", "after", "later", "back", "if", "once", "about",
        }
        words = raw_name.lower().split()
        if any(w in non_names for w in words):
            return self.session_memory.get("user_name")

        name = " ".join(word.capitalize() for word in raw_name.split())
        self.session_memory["user_name"] = name
        return name

    def get_user_name(self):
        """Retrieve the remembered student name in this session, if any."""
        return self.session_memory.get("user_name")

    def append_turn(self, query, response, records=None, active_notice=None, preserve_notice_list=False):
        """Record a completed turn and update state accordingly."""
        records_list = list(records) if records else []
        self.chat_history.append({
            "query": query,
            "response": response,
            "records": records_list,
        })
        # Preserve the identity of the list for existing main.py references.
        if len(self.chat_history) > self.max_turns_stored:
            del self.chat_history[:-self.max_turns_stored]

        # If records=None this was a conversational turn (e.g. "thanks").
        # It should not erase the last cited notices needed by "both of them".
        # Explicit records=[] still means "no evidence in this answer".
        if records is not None:
            self.set_last_answer_records(records_list)

        # Selecting item #2 from a numbered list must not destroy the list;
        # "show the 3rd one" should still reference the same original results.
        if records_list and not preserve_notice_list:
            self.set_last_results(records_list)

        # Update active_notice centrally
        if active_notice is not None:
            self.set_active_notice(active_notice)
        elif len(records_list) == 1:
            self.set_active_notice(records_list[0])
        elif len(records_list) > 1:
            self.clear_active_notice()

        # Check for user identity extraction/correction
        self.extract_and_remember_user_name(query)

    def set_last_answer_records(self, records):
        """Only notices explicitly referenced in the answer, in displayed order."""
        self.last_answer_records = list(records or [])

    def get_last_answer_records(self):
        return self.last_answer_records

    def set_active_notice(self, notice):
        """
        Centrally set the notice currently in focus and synchronize active_notice_id.
        Every retrieval or selection path that produces a single selected notice must call this.
        """
        self.active_notice = notice
        if isinstance(notice, dict):
            self.active_notice_id = notice.get("notice_id")
        elif notice is not None:
            self.active_notice_id = getattr(notice, "notice_id", None)
        else:
            self.active_notice_id = None

    def get_active_notice(self):
        """Get the notice currently in focus."""
        return self.active_notice

    def get_active_notice_id(self):
        """Get the exact notice_id of the active notice."""
        return self.active_notice_id

    def clear_active_notice(self):
        """Explicitly clear active notice context (e.g. when multiple results are listed)."""
        self.active_notice = None
        self.active_notice_id = None

    def set_last_results(self, records):
        """Set the list of recently retrieved notices in place."""
        self.last_notice_records.clear()
        if records:
            self.last_notice_records.extend(records)

    def set_last_notice_records(self, records):
        """Backward-compatible alias for set_last_results."""
        self.set_last_results(records)

    def get_last_notice_records(self):
        """Get the list of recently retrieved notices."""
        return self.last_notice_records

    def get_last_turn(self):
        """Return the most recent conversational turn."""
        return self.chat_history[-1] if self.chat_history else None

    def get_recent_history(self, max_turns=None):
        """Return formatted recent turns window for LLM prompt context."""
        return self.format_recent_history(max_turns=max_turns)

    def format_recent_history(self, max_turns=None):
        """Format the recent turns window for LLM prompt context."""
        limit = max_turns if max_turns is not None else self.history_window
        if not self.chat_history:
            return "No recent conversation history."

        if limit is not None and int(limit) <= 0:
            return "No recent conversation history."
        selected_turns = self.chat_history[-int(limit):]
        formatted = []
        for turn in selected_turns:
            if isinstance(turn, dict):
                q = turn.get("query", "")
                a = turn.get("response", "")
            elif isinstance(turn, (list, tuple)) and len(turn) >= 2:
                q, a = turn[0], turn[1]
            else:
                q, a = str(turn), ""
            # Keep prompt sizes predictable and prevent long, repeated source
            # lists from dominating the LLM context window.
            formatted.append(f"User: {str(q)[:600]}\nAssistant: {str(a)[:1600]}")
        return "\n\n".join(formatted)

    def format_context_for_understanding(self, max_turns=3):
        """
        Produce a concise summary of the conversation state specifically for
        the Query Understanding Layer.
        """
        parts = []

        # 1. Recent turns
        recent_turns = self.chat_history[-max_turns:] if self.chat_history else []
        if recent_turns:
            turn_lines = []
            for t in recent_turns:
                if isinstance(t, dict):
                    q = t.get("query", "")
                    a = str(t.get("response", ""))[:100]
                elif isinstance(t, (list, tuple)) and len(t) >= 2:
                    q = t[0]
                    a = str(t[1])[:100]
                else:
                    q = str(t)
                    a = ""
                turn_lines.append(f"- User: \"{q}\" | Assistant: \"{a}...\"")
            parts.append("Recent conversation turns:\n" + "\n".join(turn_lines))
        else:
            parts.append("Recent conversation turns: None")

        # 2. Active notice
        if self.active_notice:
            sd = self.active_notice.get("structured_data", {})
            title = sd.get("title") or self.active_notice.get("title") or "Unknown"
            date = sd.get("issue_date") or "Unknown"
            ref = sd.get("reference_no") or "Unknown"
            nid = self.active_notice_id or self.active_notice.get("notice_id") or "Unknown"
            parts.append(f"Active Notice in discussion: ID='{nid}', Title='{title}', Date='{date}', Ref='{ref}'")
        else:
            parts.append("Active Notice in discussion: None")

        # 3. Last notice list
        if self.last_notice_records:
            items = []
            for idx, r in enumerate(self.last_notice_records[:5], start=1):
                sd = r.get("structured_data", {})
                t = sd.get("title") or r.get("title") or "Notice"
                items.append(f"{idx}. {t}")
            parts.append("Last displayed notices:\n" + "\n".join(items))
        else:
            parts.append("Last displayed notices: None")

        # 4. User profile/name
        if "user_name" in self.session_memory:
            parts.append(f"Student Name: {self.session_memory['user_name']}")

        return "\n".join(parts)

    def clear(self):
        """Reset conversation state completely."""
        self.chat_history.clear()
        self.last_notice_records.clear()
        self.last_answer_records.clear()
        self.active_notice = None
        self.active_notice_id = None
        self.session_memory.clear()
