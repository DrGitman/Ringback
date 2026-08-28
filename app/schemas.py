PROOF_OF_REG = {
    "type": "object",
    "required": ["resolved", "identity_confirmed"],
    "properties": {
        "identity_confirmed": {"type": "boolean"},
        "resolved": {"type": "boolean"},
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
        "resolved": {"type": "boolean"},
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
    "required": ["category", "query_summary"],
    "properties": {
        "identity_confirmed": {"type": "boolean"},
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
