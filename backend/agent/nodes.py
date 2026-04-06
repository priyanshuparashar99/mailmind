import logging

from langgraph.types import interrupt
from langchain_groq import ChatGroq

from config import get_settings
from agent.state import EmailAgentState
from agent.tools import EmailClassification
from services import resend_client

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
    intent = classification.get("intent", "general")
    state["matched_rule"] = None
    state["proposed_action"] = {"type": "label", "value": intent}
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
        decision = interrupt(
            {
                "reason": "low_confidence",
                "proposed": state.get("proposed_action"),
            }
        )
        if isinstance(decision, str):
            state["human_decision"] = decision
        elif isinstance(decision, dict):
            decision_value = decision.get("decision") or decision.get("action")
            if decision_value is not None:
                state["human_decision"] = str(decision_value)

    return state


def act_node(state: EmailAgentState) -> EmailAgentState:
    if state.get("error"):
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
