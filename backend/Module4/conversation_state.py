"""Process-local conversation state for UniAI.

The numbered 'last_notice_records' are the original displayed list. Selecting
or asking about one item MUST NOT replace that list. New retrievals do replace
it. Deployment remains single-worker/in-memory; do not use for durable storage.
"""
import re


class ConversationState:
    def __init__(self, history_window=5, max_turns_stored=25):
        self.history_window = max(1, int(history_window))
        self.max_turns_stored = max(self.history_window, int(max_turns_stored))
        self.chat_history = []
        self.last_notice_records = []
        self.last_answer_records = []
        self.active_notice = None
        self.active_notice_id = None
        self.session_memory = {}

    def extract_and_remember_user_name(self, text):
        """Extract names only from explicit introductions/corrections."""
        message = str(text or "").strip()
        if not message:
            return self.get_user_name()
        pattern = (
            r"\b(?:my\s+name\s+is|call\s+me|correct\s+my\s+name\s+to|"
            r"change\s+my\s+name\s+to)\s+([A-Za-z]+(?:[ -][A-Za-z]+)?)\b"
        )
        match = re.search(pattern, message, re.I)
        if not match:
            match = re.fullmatch(
                r"(?:i\s+am|i['’]m)\s+([A-Za-z]+(?:[ -][A-Za-z]+)?)"
                r"[.!]?", message, re.I,
            )
        if not match and self.get_user_name():
            match = re.fullmatch(
                r"(?:correct\s+it|correction)\s*[:,]\s*"
                r"([A-Za-z]+(?:[ -][A-Za-z]+)?)\.?", message, re.I,
            )
        if not match:
            return self.get_user_name()
        name = match.group(1).strip()
        # 'Example Student' is a literal explicit name used by the suite; a
        # bare 'I am a student' is NOT an introduction.
        stopwords = {"a", "the", "here", "just", "looking", "trying", "fine",
                     "okay", "interested", "studying", "going", "searching",
                     "not", "ready", "asking", "confused", "learning", "from"}
        if any(part.lower() in stopwords for part in name.split()):
            return self.get_user_name()
        self.session_memory["user_name"] = name.title()
        return self.get_user_name()

    def get_user_name(self):
        return self.session_memory.get("user_name")

    @staticmethod
    def _same_record_in_list(record, notices):
        nid = str(record.get("notice_id") or record.get("_id") or "")
        return bool(nid) and any(
            str(item.get("notice_id") or item.get("_id") or "") == nid
            for item in notices
        )

    def append_turn(self, query, response, records=None, active_notice=None,
                    preserve_notice_list=False):
        records_list = list(records) if records else []
        self.chat_history.append({
            "query": query, "response": response, "records": records_list,
        })
        del self.chat_history[:-self.max_turns_stored]
        if records is not None:
            self.set_last_answer_records(records_list)

        # Even older paths that forget preserve_notice_list=True should not
        # erase a five-item list merely because the user asked about item #2.
        implicit_preserve = (
            not preserve_notice_list and len(self.last_notice_records) > 1
            and len(records_list) == 1
            and self._same_record_in_list(records_list[0], self.last_notice_records)
            and bool(re.search(
                r"\b(?:this|that|its|it|there|one|first|second|third|fourth|"
                r"fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th))\b",
                str(query), re.I,
            ))
        )
        if records_list and not preserve_notice_list and not implicit_preserve:
            self.set_last_results(records_list)

        if active_notice is not None:
            self.set_active_notice(active_notice)
        elif len(records_list) == 1:
            self.set_active_notice(records_list[0])
        elif len(records_list) > 1:
            self.clear_active_notice()
        self.extract_and_remember_user_name(query)

    def set_last_answer_records(self, records):
        self.last_answer_records = list(records or [])

    def get_last_answer_records(self):
        return self.last_answer_records

    def set_active_notice(self, notice):
        self.active_notice = notice
        if isinstance(notice, dict):
            self.active_notice_id = notice.get("notice_id")
        else:
            self.active_notice_id = getattr(notice, "notice_id", None) if notice else None

    def get_active_notice(self):
        return self.active_notice

    def get_active_notice_id(self):
        return self.active_notice_id

    def clear_active_notice(self):
        self.active_notice = None
        self.active_notice_id = None

    def set_last_results(self, records):
        # Important: mutate the existing list, not its identity; legacy main
        # stores references to the same list.
        self.last_notice_records.clear()
        if records:
            self.last_notice_records.extend(records)

    def set_last_notice_records(self, records):
        self.set_last_results(records)

    def get_last_notice_records(self):
        return self.last_notice_records

    def get_last_turn(self):
        return self.chat_history[-1] if self.chat_history else None

    def get_recent_history(self, max_turns=None):
        return self.format_recent_history(max_turns=max_turns)

    def format_recent_history(self, max_turns=None):
        limit = self.history_window if max_turns is None else int(max_turns)
        if limit <= 0 or not self.chat_history:
            return "No recent conversation history."
        formatted = []
        for turn in self.chat_history[-limit:]:
            if isinstance(turn, dict):
                question, answer = turn.get("query", ""), turn.get("response", "")
            elif isinstance(turn, (list, tuple)) and len(turn) >= 2:
                question, answer = turn[:2]
            else:
                question, answer = str(turn), ""
            formatted.append(f"User: {str(question)[:600]}\nAssistant: {str(answer)[:1600]}")
        return "\n\n".join(formatted)

    def format_context_for_understanding(self, max_turns=3):
        turns = self.chat_history[-max_turns:] if max_turns > 0 else []
        if turns:
            lines = [f"- User: {str(t.get('query', ''))[:300]!r} | "
                     f"Assistant: {str(t.get('response', ''))[:100]!r}"
                     for t in turns if isinstance(t, dict)]
            context = "Recent conversation turns:\n" + "\n".join(lines)
        else:
            context = "Recent conversation turns: None"
        if self.active_notice:
            sd = self.active_notice.get("structured_data") or {}
            title = sd.get("title") or self.active_notice.get("title") or "Unknown"
            day = sd.get("issue_date") or "Unknown"
            ref = sd.get("reference_no") or "Unknown"
            context += (f"\nActive Notice in discussion: ID={self.active_notice_id!r}, "
                        f"Title={title!r}, Date={day!r}, Ref={ref!r}")
        else:
            context += "\nActive Notice in discussion: None"
        if self.last_notice_records:
            names = [f"{i}. {(r.get('structured_data') or {}).get('title') or r.get('title') or 'Notice'}"
                     for i, r in enumerate(self.last_notice_records[:10], 1)]
            context += "\nLast displayed notices:\n" + "\n".join(names)
        else:
            context += "\nLast displayed notices: None"
        if self.get_user_name():
            context += f"\nStudent Name: {self.get_user_name()}"
        return context

    def clear(self):
        self.chat_history.clear()
        self.last_notice_records.clear()
        self.last_answer_records.clear()
        self.clear_active_notice()
        self.session_memory.clear()
