# paper.py
import random
from db import get_conn


def build_paper(book_id=None, chapter_ids=None, specs=None, seed=None,
                avoid_recent=True):
    """
    specs: [
      {"qtype": "单选题", "count": 8, "score": 5, "diff_min": 1, "diff_max": 3},
      ...
    ]
    返回 {"items": [...], "total_score": float, "shortage": {...}}
    """
    rng = random.Random(seed)
    specs = specs or []
    selected, used_ids, shortage = [], set(), {}

    with get_conn() as conn:
        for spec in specs:
            cnt = int(spec.get("count", 0))
            if cnt <= 0:
                continue
            sql = ("SELECT * FROM questions "
                   "WHERE qtype=? AND difficulty BETWEEN ? AND ?")
            args = [spec["qtype"], spec.get("diff_min", 1), spec.get("diff_max", 5)]
            if book_id:
                sql += " AND book_id=?"; args.append(book_id)
            if chapter_ids:
                sql += f" AND chapter_id IN ({','.join('?' * len(chapter_ids))})"
                args += list(chapter_ids)

            rows = conn.execute(sql, args).fetchall()
            # 排序策略：优先使用次数少的，同分随机打散
            if avoid_recent:
                rows = sorted(rows, key=lambda r: (r["use_count"], rng.random()))
            else:
                rows = list(rows); rng.shuffle(rows)

            picked = 0
            for r in rows:
                if picked >= cnt:
                    break
                if r["id"] in used_ids:
                    continue
                used_ids.add(r["id"])
                selected.append({**dict(r), "score": spec.get("score", 5)})
                picked += 1

            if picked < cnt:
                shortage[spec["qtype"]] = cnt - picked

    # 按题型排序，符合试卷习惯
    order = {"单选题": 0, "多选题": 1, "判断题": 2, "填空题": 3, "解答题": 4}
    selected.sort(key=lambda x: order.get(x["qtype"], 9))

    total = sum(i["score"] for i in selected)
    return {"items": selected, "total_score": total, "shortage": shortage}


def to_markdown(paper, title="数学测试卷", with_answer=False):
    """导出 Markdown（公式保留 LaTeX，可用 Pandoc 转 Word/PDF）"""
    lines = [f"# {title}", ""]
    if paper["items"]:
        lines.append(f"**总分：{paper['total_score']:g} 分**\n")

    for idx, q in enumerate(paper["items"], 1):
        lines.append(f"**{idx}.** ({q['score']:g}分) {q['content']}")
        if q.get("options"):
            for opt in q["options"]:
                lines.append(f"    {opt}")
            lines.append("")
        else:
            lines.append("")
        if with_answer:
            lines.append(f"> 答案：{q.get('answer','')}")
            if q.get("analysis"):
                lines.append(f"> 解析：{q['analysis']}")
            lines.append("")
    return "\n".join(lines)