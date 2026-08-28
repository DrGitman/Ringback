PROOF_OF_REG = {
    "type": "object",
    "required": ["resolved", "identity_confirmed"],
    "properties": {
        "identity_confirmed": {"type": "boolean"},
        "resolved": {
            "type": "boolean",
            "description": "True only if the caller confirmed this fully answered what "
            "they needed and no one needs to follow up. False if anything is still open.",
        },
        "blocker": {
            "type": "string",
            "enum": ["none", "fee_balance", "incomplete_registration", "unknown"],
        },
        "student_next_action": {"type": "string"},
        "wants_escalation": {"type": "boolean"},
    },
}

SUBJECT_CANCELLATION = {
    "type": "object",
    "required": ["resolved", "identity_confirmed"],
    "properties": {
        "identity_confirmed": {"type": "boolean"},
        "resolved": {
            "type": "boolean",
            "description": "True only if the caller confirmed this fully answered what "
            "they needed and no one needs to follow up. False if anything is still open.",
        },
        "subject_code": {"type": "string"},
        "within_deadline": {"type": "boolean"},
        "student_confirmed_drop": {"type": "boolean"},
        "fee_implication_explained": {"type": "boolean"},
        "wants_escalation": {"type": "boolean"},
    },
}

TRIAGE = {
    "type": "object",
    # "summary" is a reserved field name in CALL-E's recipient_result_schema -
    # it collides with the envelope's own result.summary (the system-generated
    # call summary CalleClient reads separately, see calle_client.py's
    # parse_call_response). Real API rejects the whole request with 400
    # recipient_result_schema_invalid if it's used here.
    "required": ["category", "query_summary", "resolved"],
    "properties": {
        "identity_confirmed": {"type": "boolean"},
        "resolved": {
            "type": "boolean",
            "description": "True only if the caller confirmed on this call that their "
            "question was fully answered and nothing further is needed - e.g. they said "
            "something like 'thanks, that's what I needed.' False if the question needs "
            "a person to follow up, wasn't covered by the reference material, or the "
            "caller didn't confirm it was answered.",
        },
        "category": {
            "type": "string",
            "enum": [
                "fees",
                "academic_records",
                "faculty",
                "accommodation",
                "exams",
                "it_support",
                "unclear",
            ],
        },
        "query_summary": {"type": "string"},
        "urgency": {"type": "string", "enum": ["routine", "deadline_driven", "urgent"]},
        "student_callback_preference": {"type": "string"},
    },
}
