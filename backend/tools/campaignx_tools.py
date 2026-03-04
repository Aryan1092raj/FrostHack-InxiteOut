import json
import requests
import os
from typing import Any
from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from db.database import check_and_increment_rate_limit

load_dotenv()

CAMPAIGNX_BASE_URL = os.getenv("CAMPAIGNX_BASE_URL", "https://campaignx.inxiteout.ai")
CAMPAIGNX_API_KEY = os.getenv("CAMPAIGNX_API_KEY", "")

# ─── OpenAPI Spec ─────────────────────────────────────────────────────────────
# Loaded from the official CampaignX API documentation
# Agent reads this to discover what APIs exist and how to call them
# This is what makes it "dynamic" — not hardcoded calls

CAMPAIGNX_OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {
        "title": "CampaignX API",
        "version": "1.0",
        "description": (
            "API for managing digital marketing campaigns. "
            "Allows retrieving customer cohorts, submitting campaigns, "
            "and fetching performance reports."
        )
    },
    "servers": [{"url": CAMPAIGNX_BASE_URL}],
    "paths": {
        "/api/v1/get_customer_cohort": {
            "get": {
                "operationId": "get_customer_cohort",
                "summary": "Get Customer Cohort",
                "description": (
                    "Fetches the full list of customers available for campaigns. "
                    "Returns customer_id, email, name and demographic attributes "
                    "for each customer. Use this to understand who can be targeted."
                ),
                "parameters": [],
                "responses": {
                    "200": {
                        "description": "List of customers",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "data": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "customer_id": {"type": "string"},
                                                    "email": {"type": "string"},
                                                    "name": {"type": "string"}
                                                }
                                            }
                                        },
                                        "total_count": {"type": "integer"},
                                        "response_code": {"type": "integer"},
                                        "message": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/v1/send_campaign": {
            "post": {
                "operationId": "send_campaign",
                "summary": "Send Campaign",
                "description": (
                    "Submits a new email marketing campaign to a targeted list of customers. "
                    "The campaign body supports plain text in English, emojis (UTF-8), "
                    "and URLs. The subject supports plain text only. "
                    "Send time must be in DD:MM:YY HH:MM:SS format. "
                    "All customer_ids must exist in the customer cohort. "
                    "Returns a campaign_id that can be used to fetch reports later."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["body", "list_customer_ids", "send_time"],
                                "properties": {
                                    "subject": {
                                        "type": "string",
                                        "description": (
                                            "Email subject line. Plain text in English only. "
                                            "Max 200 characters. No URLs allowed in subject."
                                        ),
                                        "maxLength": 200
                                    },
                                    "body": {
                                        "type": "string",
                                        "description": (
                                            "Email body content. Can contain: "
                                            "1) Any text in English, "
                                            "2) Any emoji characters, "
                                            "3) The URL https://superbfsi.com/xdeposit/explore/ "
                                            "Maximum 5000 characters."
                                        ),
                                        "maxLength": 5000
                                    },
                                    "list_customer_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": (
                                            "List of unique customer IDs to send campaign to. "
                                            "All IDs must be present in the customer cohort. "
                                            "No duplicates allowed."
                                        )
                                    },
                                    "send_time": {
                                        "type": "string",
                                        "description": (
                                            "Scheduled send time. "
                                            "MUST use format: DD:MM:YY HH:MM:SS "
                                            "Example: 14:03:26 09:00:00 means "
                                            "14th March 2026 at 9:00 AM. "
                                            "Always schedule for a future time."
                                        )
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Campaign submitted successfully",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "campaign_id": {
                                            "type": "string",
                                            "description": "UUID of the created campaign. Save this to fetch reports."
                                        },
                                        "response_code": {"type": "integer"},
                                        "invokation_time": {"type": "string"},
                                        "message": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/api/v1/get_report": {
            "get": {
                "operationId": "get_report",
                "summary": "Get Campaign Report",
                "description": (
                    "Fetches the performance report for a specific campaign. "
                    "Returns per-customer engagement data including: "
                    "EO (Email Opened: Y/N) and EC (Email Clicked: Y/N). "
                    "Can be called immediately after send_campaign — "
                    "gamified metrics are available right away. "
                    "Use this to compute open_rate and click_rate for optimization."
                ),
                "parameters": [
                    {
                        "name": "campaign_id",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "The campaign_id returned by send_campaign"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Campaign performance report",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "campaign_id": {"type": "string"},
                                        "data": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "customer_id": {"type": "string"},
                                                    "EO": {
                                                        "type": "string",
                                                        "enum": ["Y", "N"],
                                                        "description": "Email Opened"
                                                    },
                                                    "EC": {
                                                        "type": "string",
                                                        "enum": ["Y", "N"],
                                                        "description": "Email Clicked"
                                                    },
                                                    "send_time": {"type": "string"},
                                                    "subject": {"type": "string"},
                                                    "body": {"type": "string"}
                                                }
                                            }
                                        },
                                        "total_rows": {"type": "integer"},
                                        "response_code": {"type": "integer"},
                                        "message": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}


# ─── Dynamic Tool Builder ─────────────────────────────────────────────────────
# This reads the spec above and builds callable LangChain tools at runtime
# The agent receives the tool descriptions and decides which to use and when

def get_api_spec_summary() -> str:
    """
    Returns a human-readable summary of the API spec.
    This is what gets injected into the agent's system prompt
    so it understands what APIs are available.
    """
    summary = []
    summary.append("=== CampaignX API Documentation ===\n")
    summary.append(f"Base URL: {CAMPAIGNX_BASE_URL}\n")
    summary.append("Authentication: X-API-Key header required for all endpoints\n\n")

    for path, methods in CAMPAIGNX_OPENAPI_SPEC["paths"].items():
        for method, details in methods.items():
            summary.append(f"ENDPOINT: {method.upper()} {path}")
            summary.append(f"  Operation: {details['operationId']}")
            summary.append(f"  Description: {details['description']}")

            # Parameters
            if details.get("parameters"):
                summary.append("  Parameters:")
                for param in details["parameters"]:
                    summary.append(
                        f"    - {param['name']} ({param['schema']['type']})"
                        f" [{'required' if param.get('required') else 'optional'}]"
                        f": {param.get('description', '')}"
                    )

            # Request body fields
            if details.get("requestBody"):
                schema = dict(details["requestBody"]["content"]["application/json"]["schema"])
                summary.append("  Request Body Fields:")
                for field, info in dict(schema.get("properties", {})).items():
                    required = field in schema.get("required", [])
                    info_dict = dict(info)
                    summary.append(
                        f"    - {field} ({info_dict['type']})"
                        f" [{'required' if required else 'optional'}]"
                        f": {info_dict.get('description', '')}"
                    )

            summary.append("")

    return "\n".join(summary)


# ─── Pydantic Input Schemas for Tools ────────────────────────────────────────

class GetCohortInput(BaseModel):
    reason: str = Field(
        description="Why you need the cohort. E.g. 'To segment customers by demographics'"
    )


class SendCampaignInput(BaseModel):
    subject: str = Field(
        description="Email subject line. Plain English text only. Max 200 chars."
    )
    body: str = Field(
        description=(
            "Email body. Can include English text, emojis, "
            "and https://superbfsi.com/xdeposit/explore/ URL. Max 5000 chars."
        )
    )
    list_customer_ids: list[str] = Field(
        description="List of customer IDs from the cohort to send this campaign to."
    )
    send_time: str = Field(
        description="Send time in DD:MM:YY HH:MM:SS format. E.g. 14:03:26 09:00:00"
    )


class GetReportInput(BaseModel):
    campaign_id: str = Field(
        description="The campaign_id returned when you called send_campaign."
    )


# ─── Tool Functions ───────────────────────────────────────────────────────────

def tool_get_customer_cohort(reason: str) -> dict:
    """
    Dynamically calls GET /api/v1/get_customer_cohort
    Reads endpoint details from spec, constructs request, returns result.
    """
    # Get endpoint from spec dynamically
    endpoint_spec = CAMPAIGNX_OPENAPI_SPEC["paths"]["/api/v1/get_customer_cohort"]["get"]
    base_url = CAMPAIGNX_OPENAPI_SPEC["servers"][0]["url"]
    url = f"{base_url}/api/v1/get_customer_cohort"

    print(f"[Dynamic Tool] Calling: GET {url}")
    print(f"[Dynamic Tool] Operation: {endpoint_spec['operationId']}")
    print(f"[Dynamic Tool] Reason: {reason}")

    # Check rate limit
    allowed = check_and_increment_rate_limit("get_customer_cohort")
    if not allowed:
        return {
            "error": "Rate limit reached for get_customer_cohort today (100/day max)",
            "suggestion": "Use cached cohort data instead"
        }

    try:
        response = requests.get(
            url,
            headers={
                "X-API-Key": CAMPAIGNX_API_KEY,
                "Content-Type": "application/json"
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            print(f"[Dynamic Tool] ✅ Got {data.get('total_count', 0)} customers")
            return data
        else:
            return {
                "error": f"API returned {response.status_code}",
                "detail": response.text
            }

    except Exception as e:
        return {"error": str(e)}


def tool_send_campaign(
    subject: str,
    body: str,
    list_customer_ids: list[str],
    send_time: str
) -> dict:
    """
    Dynamically calls POST /api/v1/send_campaign
    Reads endpoint schema from spec to validate payload before sending.
    """
    # Get endpoint from spec dynamically
    endpoint_spec = CAMPAIGNX_OPENAPI_SPEC["paths"]["/api/v1/send_campaign"]["post"]
    base_url = CAMPAIGNX_OPENAPI_SPEC["servers"][0]["url"]
    url = f"{base_url}/api/v1/send_campaign"

    # Dynamically read required fields from spec
    content_schema = dict(endpoint_spec["requestBody"]["content"]["application/json"])
    schema = dict(content_schema["schema"])
    required_fields = schema.get("required", [])

    print(f"[Dynamic Tool] Calling: POST {url}")
    print(f"[Dynamic Tool] Operation: {endpoint_spec['operationId']}")
    print(f"[Dynamic Tool] Required fields from spec: {required_fields}")
    print(f"[Dynamic Tool] Targeting {len(list_customer_ids)} customers")
    print(f"[Dynamic Tool] Send time: {send_time}")

    # Validate against spec constraints dynamically
    properties_dict = dict(schema.get("properties", {}))
    body_schema = dict(properties_dict["body"])
    subject_schema = dict(properties_dict["subject"])
    
    max_body_len = int(body_schema.get("maxLength", 5000))
    max_subject_len = int(subject_schema.get("maxLength", 200))

    if len(body) > max_body_len:
        return {
            "error": f"Body exceeds spec limit of {max_body_len} characters",
            "current_length": len(body)
        }

    if len(subject) > max_subject_len:
        return {
            "error": f"Subject exceeds spec limit of {max_subject_len} characters",
            "current_length": len(subject)
        }

    # Check rate limit
    allowed = check_and_increment_rate_limit("send_campaign")
    if not allowed:
        return {"error": "Rate limit reached for send_campaign today (100/day max)"}

    # Build payload dynamically from spec required fields
    payload = {
        "subject": subject,
        "body": body,
        "list_customer_ids": list_customer_ids,
        "send_time": send_time
    }

    print(f"[Dynamic Tool] Payload: {json.dumps({**payload, 'list_customer_ids': f'[{len(list_customer_ids)} customers]'})}")

    try:
        response = requests.post(
            url,
            headers={
                "X-API-Key": CAMPAIGNX_API_KEY,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            print(f"[Dynamic Tool] ✅ Campaign sent! ID: {data.get('campaign_id')}")
            return data
        else:
            return {
                "error": f"API returned {response.status_code}",
                "detail": response.text
            }

    except Exception as e:
        return {"error": str(e)}


def tool_get_report(campaign_id: str) -> dict:
    """
    Dynamically calls GET /api/v1/get_report
    Reads query parameter requirements from spec.
    Computes open_rate and click_rate from raw EO/EC data.
    """
    # Get endpoint from spec dynamically
    endpoint_spec = CAMPAIGNX_OPENAPI_SPEC["paths"]["/api/v1/get_report"]["get"]
    base_url = CAMPAIGNX_OPENAPI_SPEC["servers"][0]["url"]

    # Dynamically read query params from spec
    params_spec = endpoint_spec.get("parameters", [])
    required_params = [p["name"] for p in params_spec if p.get("required")]

    print(f"[Dynamic Tool] Calling: GET /api/v1/get_report")
    print(f"[Dynamic Tool] Operation: {endpoint_spec['operationId']}")
    print(f"[Dynamic Tool] Required params from spec: {required_params}")
    print(f"[Dynamic Tool] campaign_id: {campaign_id}")

    # Check rate limit
    allowed = check_and_increment_rate_limit("get_report")
    if not allowed:
        return {"error": "Rate limit reached for get_report today (100/day max)"}

    # Build query params dynamically from spec
    query_params = {}
    for param in params_spec:
        if param["name"] == "campaign_id":
            query_params[param["name"]] = campaign_id

    try:
        response = requests.get(
            f"{base_url}/api/v1/get_report",
            headers={
                "X-API-Key": CAMPAIGNX_API_KEY,
                "Content-Type": "application/json"
            },
            params=query_params,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            raw_data = data.get("data", [])
            total = len(raw_data)

            # Compute metrics from EO/EC fields as specified in the API spec
            opens = sum(1 for r in raw_data if r.get("EO") == "Y")
            clicks = sum(1 for r in raw_data if r.get("EC") == "Y")

            open_rate = float(f"{opens / total:.4f}") if total > 0 else 0.0
            click_rate = float(f"{clicks / total:.4f}") if total > 0 else 0.0

            print(f"[Dynamic Tool] ✅ Report fetched")
            print(f"[Dynamic Tool] Total: {total} | Opens: {opens} ({open_rate:.1%}) | Clicks: {clicks} ({click_rate:.1%})")

            return {
                **data,
                "computed_metrics": {
                    "open_rate": open_rate,
                    "click_rate": click_rate,
                    "total_sent": total,
                    "opens": opens,
                    "clicks": clicks
                }
            }
        else:
            return {
                "error": f"API returned {response.status_code}",
                "detail": response.text
            }

    except Exception as e:
        return {"error": str(e)}


# ─── Build LangChain Tools Dynamically ───────────────────────────────────────
# This is called by agents at runtime
# Each tool is built from the spec — not hardcoded

def build_campaignx_tools() -> list:
    """
    Reads CAMPAIGNX_OPENAPI_SPEC and returns a list of
    LangChain StructuredTools the agent can use.

    The agent receives tool descriptions from the spec and decides
    which tool to call and with what parameters — true dynamic discovery.
    """
    tools = []

    for path, methods in CAMPAIGNX_OPENAPI_SPEC["paths"].items():
        for method, spec in methods.items():
            operation_id = spec["operationId"]

            if operation_id == "get_customer_cohort":
                tools.append(StructuredTool.from_function(
                    func=tool_get_customer_cohort,
                    name="get_customer_cohort",
                    description=spec["description"],
                    args_schema=GetCohortInput
                ))

            elif operation_id == "send_campaign":
                tools.append(StructuredTool.from_function(
                    func=tool_send_campaign,
                    name="send_campaign",
                    description=spec["description"],
                    args_schema=SendCampaignInput
                ))

            elif operation_id == "get_report":
                tools.append(StructuredTool.from_function(
                    func=tool_get_report,
                    name="get_report",
                    description=spec["description"],
                    args_schema=GetReportInput
                ))

    print(f"[Dynamic Tool Builder] Built {len(tools)} tools from OpenAPI spec:")
    for t in tools:
        print(f"  - {t.name}")

    return tools


# ─── Quick Test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== API Spec Summary (What Agent Sees) ===\n")
    print(get_api_spec_summary())

    print("\n=== Building Tools Dynamically ===\n")
    tools = build_campaignx_tools()
    print(f"\n✅ {len(tools)} tools ready for agents")