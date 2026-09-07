import json
import re

from jsonschema import Draft202012Validator

from app.config import PROJECT_ROOT


def empty_workspace():
    return {"format": "langfuse-output-collector", "version": 1, "questions": [], "reviews": []}


# The standalone page is the canonical schema source. It ships inside the image,
# so browser validation, API validation, and offline backups use the same schema.
def load_validator(name, property_name):
    html = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")
    match = re.search(rf'<script id="{name}-schema" type="application/json">(.*?)</script>', html, re.S)
    schema = json.loads(match.group(1))
    item = schema["properties"][property_name]["items"]
    Draft202012Validator.check_schema(item)
    return Draft202012Validator(item)


QUESTION = load_validator("question", "questions")
REVIEW = load_validator("review", "reviews")


def validate_workspace(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"format", "version", "questions", "reviews"}
        or value["format"] != "langfuse-output-collector"
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["questions"], list)
        or not isinstance(value["reviews"], list)
    ):
        raise ValueError("这不是本工具的 JSON 备份")
    question_ids, review_ids = set(), set()
    for entry in value["questions"]:
        if not isinstance(entry, dict) or set(entry) != {"case_id", "id_prefix", "question"}:
            raise ValueError("问题记录结构不正确")
        prefix = entry["id_prefix"]
        if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}", prefix):
            raise ValueError("编号前缀格式不正确")
        if not QUESTION.is_valid(entry["question"]):
            raise ValueError("问题或画像不符合 QuestionOutput 格式")
        expected = f"{prefix}-{entry['question']['local_id']}"
        if entry["case_id"] != expected or expected in question_ids:
            raise ValueError("问题编号不匹配或重复")
        question_ids.add(expected)
    for review in value["reviews"]:
        if not REVIEW.is_valid(review):
            raise ValueError("问诊材料不符合 ReviewOutput 格式")
        if review["case_id"] in review_ids:
            raise ValueError("问诊材料编号重复")
        review_ids.add(review["case_id"])
    return value
