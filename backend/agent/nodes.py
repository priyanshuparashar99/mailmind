import logging

from langgraph.types import interrupt
from langchain_groq import ChatGroq

from config import get_settings
from agent.state import EmailAgentState
from agent.tools import EmailClassification
from models import EmailLog, HitlItem, session_scope
from services import resend_client
from services import rules_engine

LOGGER = logging.getLogger(__name__)


def fetch_content_node(state: EmailAgentState) -> EmailAgentState:
    try:
        state["body"] = resend_client.get_email_body(state["email_id"])
        state["attachments"] = resend_client.get_attachments(state["email_id"])
    except Exception as exc:
        state["error"] = f"fetch_content_failed: {exc}"
        LOGGER.exception(
            "Failed to fetch email content for email_id=%s", state["email_id"]
        )
    return state


def classify_node(state: EmailAgentState) -> EmailAgentState:
    if state.get("error"):
        return state

    try:
        settings = get_settings()
        model = settings.llm_model
        truncated_body = (state.get("body") or "")[:2000]
        user_content = f"Subject: {state.get('subject', '')}\n\nBody:\n{truncated_body}"

        llm = ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            temperature=0,
        )
        structured_llm = llm.with_structured_output(
            EmailClassification,
            method="json_schema",
        )

        parsed = structured_llm.invoke(
            [
                {
                    "role": "system",
                    "content": "You are an email intent classifier. Extract structured metadata from the email.",
                },
                {"role": "user", "content": user_content},
            ]
        )
        if not isinstance(parsed, EmailClassification):
            parsed = EmailClassification.model_validate(parsed)

        state["classification"] = parsed.model_dump()

        threshold = settings.hitl_confidence_threshold
        state["hitl_required"] = parsed.confidence < threshold
    except Exception as exc:
        state["error"] = f"classification_failed: {exc}"
        LOGGER.exception("Classification failed for email_id=%s", state["email_id"])

    return state


def rule_match_node(state: EmailAgentState) -> EmailAgentState:
    if state.get("error"):
        return state

    classification = state.get("classification") or {}
    with session_scope() as session:
        matched_rule = rules_engine.match_rule(classification, session)

    if matched_rule is None:
        state["matched_rule"] = None
        state["proposed_action"] = {
            "type": "label",
            "value": classification.get("intent", "general"),
        }
    else:
        state["matched_rule"] = {
            "id": getattr(matched_rule, "id", None),
            "name": matched_rule.name,
            "intent_match": matched_rule.intent_match,
            "urgency_min": matched_rule.urgency_min,
            "action_type": matched_rule.action_type,
            "action_value": matched_rule.action_value,
            "require_hitl": matched_rule.require_hitl,
        }
        state["proposed_action"] = {
            "type": matched_rule.action_type,
            "value": matched_rule.action_value,
        }
        if matched_rule.require_hitl:
            state["hitl_required"] = True

    LOGGER.info(
        "rule_match_node: email_id=%s proposed_action=%s",
        state["email_id"],
        state["proposed_action"],
    )
    return state


def hitl_gate_node(state: EmailAgentState) -> EmailAgentState:
    if state.get("error"):
        return state

    if state.get("hitl_required") and not state.get("human_decision"):
        with session_scope() as session:
            pending = (
                session.query(HitlItem)
                .filter(
                    HitlItem.email_id == state["email_id"], HitlItem.status == "pending"
                )
                .first()
            )
            if pending is None:
                session.add(
                    HitlItem(
                        email_id=state["email_id"],
                        subject=state.get("subject", ""),
                        from_addr=state.get("from_addr", ""),
                        classification=state.get("classification") or {},
                        proposed_action=state.get("proposed_action") or {},
                        status="pending",
                    )
                )

        decision = interrupt(
            {
                "reason": "low_confidence",
                "email_id": state.get("email_id"),
                "proposed": state.get("proposed_action"),
            }
        )
        if isinstance(decision, str):
            state["human_decision"] = decision
        elif isinstance(decision, dict):
            decision_value = decision.get("decision") or decision.get("action")
            if decision_value is not None:
                state["human_decision"] = str(decision_value)
            if isinstance(decision.get("action"), dict):
                state["proposed_action"] = decision["action"]

    return state


def act_node(state: EmailAgentState) -> EmailAgentState:
    if state.get("error"):
        return state

    if state.get("human_decision") == "reject":
        state["action_result"] = "skipped_rejected"
        return state

    action = state.get("proposed_action") or {}
    action_type = action.get("type")

    try:
        if action_type == "label":
            resend_client.noop_label(
                state["email_id"], str(action.get("value", "general"))
            )
        elif action_type == "reply":
            LOGGER.info(
                "reply action stub: email_id=%s action=%s", state["email_id"], action
            )
        elif action_type == "forward":
            LOGGER.info(
                "forward action stub: email_id=%s action=%s",
                state["email_id"],
                action,
            )
        elif action_type == "escalate":
            LOGGER.info(
                "escalate action stub: email_id=%s action=%s",
                state["email_id"],
                action,
            )
        else:
            LOGGER.info(
                "unknown action stub: email_id=%s action=%s", state["email_id"], action
            )

        state["action_result"] = "success"
    except Exception as exc:
        state["error"] = f"action_failed: {exc}"
        state["action_result"] = "failed"
        LOGGER.exception("Action execution failed for email_id=%s", state["email_id"])

    return state


def log_result_node(state: EmailAgentState) -> EmailAgentState:
    intent = (state.get("classification") or {}).get("intent")
    classification = state.get("classification") or {}
    matched_rule = state.get("matched_rule") or {}
    action = state.get("proposed_action") or {}

    with session_scope() as session:
        existing = (
            session.query(EmailLog)
            .filter(EmailLog.email_id == state["email_id"])
            .first()
        )
        payload = {
            "from_addr": state.get("from_addr", ""),
            "subject": state.get("subject", ""),
            "intent": str(classification.get("intent", "general")),
            "urgency": int(classification.get("urgency", 1)),
            "confidence": float(classification.get("confidence", 0.0)),
            "matched_rule_id": matched_rule.get("id"),
            "action_type": str(action.get("type", "label")),
            "action_value": action.get("value"),
            "hitl_required": bool(state.get("hitl_required", False)),
            "human_decision": state.get("human_decision"),
            "action_result": state.get("action_result") or "unknown",
        }
        if existing is None:
            session.add(EmailLog(email_id=state["email_id"], **payload))
        else:
            for key, value in payload.items():
                setattr(existing, key, value)

    print(
        "mailmind_result",
        {
            "email_id": state.get("email_id"),
            "intent": intent,
            "action_result": state.get("action_result"),
            "hitl_required": state.get("hitl_required"),
            "error": state.get("error"),
        },
    )
    return state
