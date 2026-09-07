from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountName(Contract):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class LoginInput(Contract):
    username: str = Field(min_length=3, max_length=254, validation_alias=AliasChoices("email", "username"))
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class RegisterInput(Contract):
    # Syntax only: no DNS, provider allowlist, mail delivery, or ownership checks.
    email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*$",
    )
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class CreateUserInput(AccountName):
    display_name: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=1, max_length=128)


class UserUpdate(Contract):
    active: bool | None = None
    password: SecretStr | None = Field(default=None, min_length=1, max_length=128)


class PasswordInput(Contract):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=1, max_length=128)


class WorkspaceInput(Contract):
    account_id: str
    revision: int = Field(ge=0, strict=True)
    state: dict
