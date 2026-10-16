from pydantic import BaseModel


def strip_titles(schema: dict) -> dict:
    def walk(obj):
        if isinstance(obj, dict):
            obj.pop("title", None)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(schema)


class BaseStructuredOutput(BaseModel):
    model_config = {
        "extra": "forbid",
        "json_schema_extra": strip_titles,
    }