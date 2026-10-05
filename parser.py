# parser.py
import re

OPTION_RE = re.compile(r"^\s*([A-Ha-h])\s*[\.、．\)）]\s*(.+)$")
QNUM_RE = re.compile(r"^\s*(\d{1,3})\s*[\.、．\)）]\s*(.+)$")
ANSWER_RE = re.compile(r"^\s*(?:【答案】|答案|参考答案)\s*[:：]?\s*(.*)$")
ANALYSIS_RE = re.compile(r"^\s*(?:【解析】|解析|解答|【详解】)\s*[:：]?\s*(.*)$")
TYPE_RE = re.compile(r"[（(【\[]?\s*(单选|多选|填空|解答|判断)题?\s*[)）】\]]?")

TYPE_ALIAS = {
    "单选": "单选题", "多选": "多选题",
    "填空": "填空题", "解答": "解答题", "判断": "判断题",
}


def parse_questions(text: str):
    """
    解析形如：
        1. 已知函数 f(x)=x^2+1，则 f(2)=（  ）
        A. 3   B. 4   C. 5   D. 6
        答案：C
        解析：代入 x=2 得 f(2)=5。
    返回 dict 列表：{number, content, options, answer, analysis, qtype}
    """
    lines = text.splitlines()
    blocks, cur, mode = [], None, None

    def flush():
        nonlocal cur
        if cur:
            blocks.append(cur)
            cur = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # 新题目
        m = QNUM_RE.match(line)
        if m and not OPTION_RE.match(line):
            flush()
            cur = {"number": m.group(1), "stem": [m.group(2)],
                   "options": [], "answer": "", "analysis": ""}
            mode = "stem"
            continue

        if cur is None:
            continue

        # 选项
        mo = OPTION_RE.match(line)
        if mo and mode in ("stem", "option"):
            cur["options"].append(f"{mo.group(1).upper()}. {mo.group(2).strip()}")
            mode = "option"
            continue

        # 答案
        ma = ANSWER_RE.match(line)
        if ma:
            cur["answer"] = ma.group(1).strip()
            mode = "answer"
            continue

        # 解析
        mn = ANALYSIS_RE.match(line)
        if mn:
            cur["analysis"] = mn.group(1).strip()
            mode = "analysis"
            continue

        # 续行
        if mode == "stem":
            cur["stem"].append(line)
        elif mode == "option" and cur["options"]:
            cur["options"][-1] += " " + line
        elif mode == "answer":
            cur["answer"] += " " + line
        elif mode == "analysis":
            cur["analysis"] += " " + line

    flush()

    results = []
    for b in blocks:
        content = "\n".join(b["stem"]).strip()
        qtype = _guess_type(b, content)
        results.append({
            "number": b["number"],
            "content": content,
            "options": b["options"],
            "answer": b["answer"],
            "analysis": b["analysis"],
            "qtype": qtype,
        })
    return results


def _guess_type(block, content):
    # 1) 题干中显式标注
    m = TYPE_RE.search(content)
    if m and m.group(1) in TYPE_ALIAS:
        return TYPE_ALIAS[m.group(1)]
    # 2) 有选项 → 选择题
    if block["options"]:
        # 多个答案字母 → 多选
        ans = block["answer"].upper().replace(" ", "")
        letters = [c for c in ans if c.isalpha()]
        return "多选题" if len(set(letters)) > 1 else "单选题"
    # 3) 题干含括号空位 → 填空
    if re.search(r"[（(]\s*[)）]", content):
        return "填空题"
    return "解答题"