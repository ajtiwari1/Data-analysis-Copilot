from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeneratedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str | None = Field(default=None, min_length=1, max_length=4000)
    clarification: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_request(self) -> "GeneratedSQL":
        if (self.sql is None) == (self.clarification is None):
            raise ValueError("Provide exactly one of sql or clarification")
        if self.sql is not None and not self.sql.strip():
            raise ValueError("SQL cannot be blank")
        return self


class SQLAgentError(RuntimeError):
    """The agent could not safely produce an approved analytics operation."""
