from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_source_types: list[
        Literal["local_article", "web", "government"]
    ] = Field(default_factory=list)
    same_cluster_only: bool = False
    exclude_selected_article: bool = True
    allowed_relationships: list[Literal["coverage", "redundant"]] = Field(
        default_factory=list
    )
    allowed_domains: list[str] = Field(default_factory=list)
    require_full_page_fetch: bool = True
    persist_evidence: bool = True
    max_excerpt_words: int = Field(default=350, ge=50, le=2000)

    @property
    def allowed_domain_set(self) -> set[str]:
        return {domain.strip().casefold() for domain in self.allowed_domains if domain.strip()}


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=5, max_length=500)
    enabled: bool
    agent_callable: bool
    max_calls_per_article: int = Field(ge=0, le=20)
    max_results: int = Field(ge=0, le=50)
    permissions: ToolPermissions


class SupplementToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    tools: dict[str, ToolPolicy]

    @model_validator(mode="after")
    def require_known_tools(self) -> "SupplementToolPolicy":
        required = {
            "search_local",
            "web_search",
            "mcp_government_search",
            "collect_chunk",
        }
        missing = required - set(self.tools)
        unknown = set(self.tools) - required
        if missing or unknown:
            raise ValueError(
                f"Supplement tool policy mismatch; missing={sorted(missing)}, "
                f"unknown={sorted(unknown)}"
            )
        return self

    def tool(self, name: str) -> ToolPolicy:
        return self.tools[name]

    def llm_tool_list(self, names: list[str]) -> list[dict[str, object]]:
        definitions: list[dict[str, object]] = []
        for name in names:
            tool = self.tool(name)
            if not tool.enabled or not tool.agent_callable:
                continue
            if name == "collect_chunk":
                input_schema = {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_call_id", "max_chunks"],
                    "properties": {
                        "source_call_id": {"type": "string"},
                        "max_chunks": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": min(20, tool.max_results),
                        },
                    },
                }
            else:
                input_schema = {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 3, "maxLength": 500}
                    },
                }
            definitions.append(
                {
                    "name": name,
                    "description": tool.description,
                    "input_schema": input_schema,
                }
            )
        return definitions


def _default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "supplement_tools.yaml"


@lru_cache(maxsize=8)
def load_supplement_tool_policy(path: str | None = None) -> SupplementToolPolicy:
    policy_path = Path(path) if path else _default_policy_path()
    if not policy_path.is_absolute():
        policy_path = Path(__file__).resolve().parents[2] / policy_path
    with policy_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return SupplementToolPolicy.model_validate(payload)
