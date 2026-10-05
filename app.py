# app.py
import io
import uuid
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

import db
from db import IMG_DIR
from parser import parse_questions
from paper import build_paper, to_markdown

st.set_page_config(page_title="高中数学题库系统", layout="wide", page_icon="📐")
db.init_db()

QTYPES = ["单选题", "多选题", "填空题", "判断题", "解答题"]
DIFF_LABEL = {1: "★ 很易", 2: "★★ 较易", 3: "★★★ 中等", 4: "★★★★ 较难", 5: "★★★★★ 很难"}


# ============================================================
# 公共组件
# ============================================================
def render_question_body(content: str, options=None):
    """渲染题干 + 图片占位 [IMG:xxx.png]"""
    import re
    parts = re.split(r"\[IMG:([^\]]+)\]", content or "")
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                st.markdown(part)
        else:
            p = IMG_DIR / part
            if p.exists():
                st.image(str(p), width=420)
            else:
                st.caption(f"（图片缺失：{part}）")
    if options:
        for opt in options:
            st.markdown(f"　　{opt}")


def book_selector(key, allow_none=False):
    books = db.list_books()
    opts = [(None, "（全部）")] if allow_none else []
    opts += [(b["id"], b["name"]) for b in books]
    if not opts:
        return None, None
    labels = [l for _, l in opts]
    idx = st.selectbox("教材", range(len(labels)),
                       format_func=lambda i: labels[i], key=f"book_{key}")
    return opts[idx][0], labels[idx]


def chapter_multiselect(book_id, key):
    paths = db.chapter_paths(book_id)
    if not paths:
        return []
    id2path = dict(paths)
    picked = st.multiselect(
        "章节（可多选，含子章节）",
        options=[p[0] for p in paths],
        format_func=lambda i: id2path.get(i, str(i)),
        key=f"chap_{key}")
    # 展开为含所有子章节
    expanded = set()
    for cid in picked:
        expanded.update(db.descendant_chapter_ids(cid))
    return list(expanded)


# ============================================================
# 页面 1：题目录入
# ============================================================
def page_input():
    st.header("📝 题目录入")
    tab1, tab2 = st.tabs(["单题录入", "批量导入"])

    # ---------- 单题 ----------
    with tab1:
        books = db.list_books()
        if not books:
            st.warning("请先在「⚙️ 数据与设置」中创建教材与章节。")
            return

        c1, c2 = st.columns(2)
        with c1:
            book_id, _ = book_selector("single")
        with c2:
            paths = db.chapter_paths(book_id)
            id2path = {None: "（未分类）", **{i: p for i, p in paths}}
            cid = st.selectbox("章节", list(id2path.keys()),
                               format_func=lambda i: id2path[i], key="single_chap")

        with st.form("form_single", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns(4)
            qtype = c1.selectbox("题型", QTYPES)
            diff = c2.selectbox("难度", list(DIFF_LABEL.keys()),
                                index=2, format_func=lambda x: DIFF_LABEL[x])
            score = c3.number_input("分值", 0.5, 50.0, 5.0, 0.5)
            source = c4.text_input("来源", placeholder="如：2023 全国卷 I")

            st.caption("题干支持 LaTeX，行内公式用 `$...$`，独立公式用 `$$...$$`；"
                       "插入图片请在文中写 `[IMG:文件名]`")
            content = st.text_area("题干 *", height=140)

            options_text = st.text_area(
                "选项（仅选择题填写，每行一个，如 `A. 3`）", height=100)

            c1, c2 = st.columns(2)
            answer = c1.text_area("答案", height=80)
            analysis = c2.text_area("解析", height=80)
            tags = st.text_input("标签（逗号分隔）", placeholder="函数,单调性,导数")

            uploaded = st.file_uploader(
                "插图（可选，多张）", type=["png", "jpg", "jpeg", "gif"],
                accept_multiple_files=True)

            submitted = st.form_submit_button("💾 保存题目", type="primary")

        if submitted:
            if not content.strip():
                st.error("题干不能为空")
            else:
                opts = [l.strip() for l in options_text.splitlines() if l.strip()]
                # 保存图片，并在题干末尾追加占位符
                markers = []
                for f in uploaded or []:
                    ext = Path(f.name).suffix.lower()
                    fname = f"{uuid.uuid4().hex[:12]}{ext}"
                    (IMG_DIR / fname).write_bytes(f.getbuffer())
                    markers.append(f"[IMG:{fname}]")
                full_content = content.strip()
                if markers:
                    full_content += "\n" + " ".join(markers)

                qid = db.add_question({
                    "book_id": book_id, "chapter_id": cid, "qtype": qtype,
                    "difficulty": diff, "content": full_content,
                    "options": opts, "answer": answer.strip(),
                    "analysis": analysis.strip(), "tags": tags.strip(),
                    "source": source.strip(), "score": score,
                })
                for m in markers:
                    db.add_image(qid, m[5:-1], str(IMG_DIR / m[5:-1]))
                st.success(f"✅ 已保存，题目 ID = {qid}")
                st.rerun()

    # ---------- 批量导入 ----------
    with tab2:
        st.markdown("""**支持的文本格式示例：**
    已知函数 f(x)=x^2+1，则 f(2)=（ ）
    A. 3
    B. 4
    C. 5
    D. 6
    答案：C
    解析：代入 x=2，得 f(2)=5。

    计算  的值。
    答案：
    f
    r
    a
    c
    12
    frac12

    text
    """)
        raw = st.text_area("粘贴题目文本", height=280, key="batch_text")

        c1, c2, c3 = st.columns(3)
        with c1:
            book_id, _ = book_selector("batch")
        with c2:
            paths = db.chapter_paths(book_id)
            id2path = {None: "（未分类）", **{i: p for i, p in paths}}
            cid = st.selectbox("统一归属章节", list(id2path.keys()),
                               format_func=lambda i: id2path[i], key="batch_chap")
        with c3:
            default_score = st.number_input("默认分值", 0.5, 50.0, 5.0, 0.5,
                                            key="batch_score")

        if st.button("🔍 解析预览", key="btn_parse"):
            st.session_state["parsed"] = parse_questions(raw)

        parsed = st.session_state.get("parsed", [])
        if parsed:
            st.success(f"共解析出 {len(parsed)} 道题")
            preview = pd.DataFrame([{
                "序号": p["number"],
                "题型": p["qtype"],
                "题干": p["content"][:50] + ("..." if len(p["content"]) > 50 else ""),
                "选项数": len(p["options"]),
                "答案": p["answer"][:20],
            } for p in parsed])
            st.dataframe(preview, use_container_width=True, hide_index=True)

            if st.button("✅ 确认导入全部", type="primary"):
                for p in parsed:
                    db.add_question({
                        "book_id": book_id, "chapter_id": cid,
                        "qtype": p["qtype"], "difficulty": 3,
                        "content": p["content"], "options": p["options"],
                        "answer": p["answer"], "analysis": p["analysis"],
                        "score": default_score,
                    })
                st.success(f"成功导入 {len(parsed)} 道题")
                st.session_state["parsed"] = []
                st.rerun()

    # ============================================================
    # 页面 2：题库浏览
    # ============================================================
    def page_browse():
        st.header("📚 题库浏览")
        st.caption(f"题库总量：{db.count_questions()} 题")

        c1, c2, c3, c4 = st.columns([1.2, 2, 1, 1.2])
        with c1:
            book_id, _ = book_selector("browse", allow_none=True)
        with c2:
            chap_ids = chapter_multiselect(book_id, "browse") if book_id else []
        with c3:
            qtype = st.selectbox("题型", ["全部"] + QTYPES, key="browse_type")
        with c4:
            keyword = st.text_input("关键词搜索", key="browse_kw")

        diff = st.slider("难度范围", 1, 5, (1, 5), key="browse_diff")

        questions = db.search_questions(
            book_id=book_id,
            chapter_ids=chap_ids or None,
            qtype=None if qtype == "全部" else qtype,
            keyword=keyword or None,
            limit=500,
        )
        questions = [q for q in questions if diff[0] <= q["difficulty"] <= diff[1]]

        st.markdown(f"**共 {len(questions)} 道题**")

        if not questions:
            st.info("没有符合条件的题目")
            return

        for q in questions:
            title = (f"#{q['id']} · {q['qtype']} · {DIFF_LABEL.get(q['difficulty'], '')} · "
                     f"{q.get('chapter_name') or '未分类'} · 用过 {q['use_count']} 次")
            with st.expander(title, expanded=False):
                render_question_body(q["content"], json.loads(q["options"] or "[]"))
                c1, c2 = st.columns([1, 3])
                with c1:
                    if st.button("显示答案", key=f"ans_{q['id']}"):
                        st.session_state[f"show_{q['id']}"] = True
                if st.session_state.get(f"show_{q['id']}"):
                    st.markdown(f"**答案：** {q['answer']}")
                    if q["analysis"]:
                        st.markdown(f"**解析：** {q['analysis']}")
                if q.get("tags"):
                    st.caption(f"标签：{q['tags']}　来源：{q.get('source', '')}")

                cc1, cc2, _ = st.columns([1, 1, 5])
                if cc1.button("🗑 删除", key=f"del_{q['id']}"):
                    db.delete_question(q["id"])
                    st.rerun()
                if cc2.button("✏️ 编辑", key=f"edit_{q['id']}"):
                    st.session_state["edit_id"] = q["id"]
                    st.rerun()

        # 编辑面板
        eid = st.session_state.get("edit_id")
        if eid:
            q = db.get_question(eid)
            if q:
                st.divider()
                st.subheader(f"✏️ 编辑题目 #{eid}")
                with st.form("form_edit"):
                    c1, c2, c3 = st.columns(3)
                    qtype = c1.selectbox("题型", QTYPES, index=QTYPES.index(q["qtype"]))
                    diff = c2.selectbox("难度", list(DIFF_LABEL.keys()),
                                        index=q["difficulty"] - 1,
                                        format_func=lambda x: DIFF_LABEL[x])
                    score = c3.number_input("分值", 0.5, 50.0, float(q["score"]), 0.5)
                    content = st.text_area("题干", q["content"], height=140)
                    options_text = st.text_area(
                        "选项（每行一个）",
                        "\n".join(json.loads(q["options"] or "[]")), height=100)
                    c1, c2 = st.columns(2)
                    answer = c1.text_area("答案", q["answer"] or "", height=80)
                    analysis = c2.text_area("解析", q["analysis"] or "", height=80)
                    tags = st.text_input("标签", q["tags"] or "")

                    b1, b2 = st.columns([1, 6])
                    save = b1.form_submit_button("保存", type="primary")
                    cancel = b2.form_submit_button("取消")

                if save:
                    db.update_question(eid, {
                        "qtype": qtype, "difficulty": diff, "content": content,
                        "options": [l.strip() for l in options_text.splitlines() if l.strip()],
                        "answer": answer.strip(), "analysis": analysis.strip(),
                        "tags": tags.strip(), "score": score,
                    })
                    st.session_state["edit_id"] = None
                    st.success("已更新")
                    st.rerun()
                if cancel:
                    st.session_state["edit_id"] = None
                    st.rerun()

    # ============================================================
    # 页面 3：组卷与导出
    # ============================================================
    def page_paper():
        st.header("🎯 组卷与导出")

        c1, c2 = st.columns([1, 2])
        with c1:
            book_id, book_label = book_selector("paper", allow_none=True)
        with c2:
            chap_ids = chapter_multiselect(book_id, "paper") if book_id else []

        st.subheader("题型配置")
        default_df = pd.DataFrame([
            {"启用": True, "题型": "单选题", "数量": 8, "每题分值": 5.0, "难度下限": 1, "难度上限": 3},
            {"启用": True, "题型": "多选题", "数量": 4, "每题分值": 5.0, "难度下限": 2, "难度上限": 4},
            {"启用": False, "题型": "判断题", "数量": 5, "每题分值": 3.0, "难度下限": 1, "难度上限": 2},
            {"启用": True, "题型": "填空题", "数量": 4, "每题分值": 5.0, "难度下限": 2, "难度上限": 4},
            {"启用": True, "题型": "解答题", "数量": 3, "每题分值": 12.0, "难度下限": 3, "难度上限": 5},
        ])
        edited = st.data_editor(
            default_df, use_container_width=True, hide_index=True,
            column_config={
                "启用": st.column_config.CheckboxColumn("启用"),
                "题型": st.column_config.SelectboxColumn("题型", options=QTYPES),
                "数量": st.column_config.NumberColumn("数量", min_value=0, max_value=50, step=1),
                "每题分值": st.column_config.NumberColumn("每题分值", min_value=0.5, max_value=50.0, step=0.5),
                "难度下限": st.column_config.NumberColumn("难度下限", min_value=1, max_value=5, step=1),
                "难度上限": st.column_config.NumberColumn("难度上限", min_value=1, max_value=5, step=1),
            })

        c1, c2 = st.columns([1, 3])
        seed = c1.number_input("随机种子（0=每次不同）", 0, 999999, 0, 1)
        avoid_recent = c2.checkbox("优先选用使用次数少的题目", value=True)

        if st.button("🎲 生成试卷", type="primary"):
            specs = []
            for _, row in edited.iterrows():
                if not row["启用"] or row["数量"] <= 0:
                    continue
                specs.append({
                    "qtype": row["题型"], "count": int(row["数量"]),
                    "score": float(row["每题分值"]),
                    "diff_min": int(row["难度下限"]), "diff_max": int(row["难度上限"]),
                })
            paper = build_paper(
                book_id=book_id, chapter_ids=chap_ids or None, specs=specs,
                seed=seed if seed else None, avoid_recent=avoid_recent)
            st.session_state["paper"] = paper
            if paper["shortage"]:
                st.warning("题库中以下题型数量不足：" +
                           "，".join(f"{k} 缺 {v} 题" for k, v in paper["shortage"].items()))

        paper = st.session_state.get("paper")
        if not paper or not paper["items"]:
            return

        st.divider()
        st.subheader(f"📄 试卷预览（共 {len(paper['items'])} 题，总分 {paper['total_score']:g} 分）")

        with st.expander("查看试卷内容", expanded=True):
            for i, q in enumerate(paper["items"], 1):
                st.markdown(f"**{i}.** （{q['score']:g} 分）")
                render_question_body(q["content"], json.loads(q["options"] or "[]"))
                st.markdown("---")

        with st.expander("查看答案与解析"):
            for i, q in enumerate(paper["items"], 1):
                st.markdown(f"**{i}.** 答案：{q['answer']}")
                if q["analysis"]:
                    st.caption(f"解析：{q['analysis']}")

        # 导出
        title = st.text_input("试卷标题", "高中数学测试卷")
        st.download_button(
            "⬇️ 下载 Markdown（含答案）",
            to_markdown(paper, title, with_answer=True).encode("utf-8"),
            file_name=f"{title}_含答案.md", mime="text/markdown")
        st.download_button(
            "⬇️ 下载 Markdown（学生版）",
            to_markdown(paper, title, with_answer=False).encode("utf-8"),
            file_name=f"{title}_学生版.md", mime="text/markdown")
        st.caption("提示：Markdown 可用 Pandoc 转成 Word/PDF，公式保留 LaTeX："
                   "`pandoc 试卷.md -o 试卷.docx`")

        if st.button("📌 标记为已使用（使用次数 +1）"):
            db.inc_use_count([q["id"] for q in paper["items"]])
            st.success("已更新使用次数")

    # ============================================================
    # 页面 4：错题追踪
    # ============================================================
    def page_wrong():
        st.header("❌ 错题追踪")

        students = db.list_students()
        if not students:
            st.warning("请先在「👥 学生管理」中添加学生")
            return

        id2name = {s["id"]: f"{s['class_name']} {s['name']}".strip() for s in students}
        sid = st.selectbox("选择学生", list(id2name.keys()),
                           format_func=lambda i: id2name[i])

        tab1, tab2 = st.tabs(["📋 错题清单", "➕ 添加错题"])

        with tab1:
            rows = db.list_wrong(sid)
            if not rows:
                st.info("该学生暂无错题记录")
            else:
                st.markdown(f"**共 {len(rows)} 道错题**")
                # 知识点分布
                dist = {}
                for r in rows:
                    key = r.get("chapter_name") or "未分类"
                    dist[key] = dist.get(key, 0) + 1
                if dist:
                    st.bar_chart(pd.Series(dist, name="错题数"))

                for r in rows:
                    with st.expander(
                            f"#{r['question_id']} · {r['qtype']} · 错 {r['wrong_count']} 次 · "
                            f"{r.get('chapter_name') or '未分类'}"):
                        render_question_body(r["content"], json.loads(r["options"] or "[]"))
                        st.markdown(f"**答案：** {r['answer']}")
                        if r["analysis"]:
                            st.markdown(f"**解析：** {r['analysis']}")
                        if r.get("note"):
                            st.caption(f"备注：{r['note']}")
                        if st.button("✅ 已掌握，移除", key=f"rm_{r['id']}"):
                            db.remove_wrong(r["id"])
                            st.rerun()

                if st.button("🎯 生成错题重练卷"):
                    items = []
                    for r in rows:
                        items.append({**r, "score": 5})
                    paper = {"items": items, "total_score": 5 * len(items), "shortage": {}}
                    md = to_markdown(paper, f"{id2name[sid]} 错题重练", with_answer=True)
                    st.download_button("⬇️ 下载错题重练卷（Markdown）",
                                       md.encode("utf-8"),
                                       file_name=f"错题重练_{id2name[sid]}.md")

        with tab2:
            st.markdown("**方式一：输入题号**")
            c1, c2, c3 = st.columns([2, 1, 3])
            qid = c1.number_input("题目 ID", 1, 999999, 1, 1)
            note = c3.text_input("错误原因（可选）", key="wrong_note")
            if c2.button("添加", key="add_wrong_by_id"):
                if db.get_question(qid):
                    db.add_wrong(sid, int(qid), note)
                    st.success(f"已添加题目 #{qid}")
                    st.rerun()
                else:
                    st.error("题目不存在")

            st.divider()
            st.markdown("**方式二：搜索后勾选添加**")
            kw = st.text_input("关键词", key="wrong_kw")
            if kw:
                found = db.search_questions(keyword=kw, limit=30)
                for q in found:
                    c1, c2 = st.columns([6, 1])
                    c1.markdown(f"**#{q['id']}** {q['content'][:80]}")
                    if c2.button("加入错题", key=f"aw_{q['id']}"):
                        db.add_wrong(sid, q["id"])
                        st.success(f"已添加 #{q['id']}")
                        st.rerun()

    # ============================================================
    # 页面 5：学生管理
    # ============================================================
    def page_students():
        st.header("👥 学生管理")

        with st.form("form_student"):
            c1, c2, c3 = st.columns([2, 2, 1])
            name = c1.text_input("姓名")
            cls = c2.text_input("班级")
            if c3.form_submit_button("添加", type="primary") and name.strip():
                db.add_student(name.strip(), cls.strip())
                st.rerun()

        students = db.list_students()
        if students:
            df = pd.DataFrame([{
                "ID": s["id"], "姓名": s["name"], "班级": s["class_name"] or "",
                "创建时间": s["created_at"] or ""
            } for s in students])
            st.dataframe(df, use_container_width=True, hide_index=True)

            del_id = st.selectbox("删除学生", [s["id"] for s in students],
                                  format_func=lambda i: next(
                                      f"{s['class_name']} {s['name']}" for s in students if s["id"] == i))
            if st.button("🗑 删除该学生及其错题记录"):
                db.delete_student(del_id)
                st.rerun()

    # ============================================================
    # 页面 6：数据与设置
    # ============================================================
    def page_settings():
        st.header("⚙️ 数据与设置")

        tab1, tab2, tab3 = st.tabs(["教材章节", "数据库备份", "初始化示例"])

        with tab1:
            st.subheader("教材")
            with st.form("form_book"):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                bname = c1.text_input("教材名称")
                pub = c2.text_input("出版社")
                grade = c3.text_input("年级")
                if c4.form_submit_button("添加") and bname.strip():
                    db.add_book(bname.strip(), pub.strip(), grade.strip())
                    st.rerun()

            books = db.list_books()
            if books:
                st.dataframe(pd.DataFrame(books)[["id", "name", "publisher", "grade"]],
                             use_container_width=True, hide_index=True)
                del_b = st.selectbox("删除教材（会级联删除章节）",
                                     [b["id"] for b in books],
                                     format_func=lambda i: next(b["name"] for b in books if b["id"] == i))
                if st.button("删除教材"):
                    db.delete_book(del_b)
                    st.rerun()

            st.divider()
            st.subheader("章节")
            if books:
                bid = st.selectbox("所属教材", [b["id"] for b in books],
                                   format_func=lambda i: next(b["name"] for b in books if b["id"] == i),
                                   key="chap_book")
                paths = db.chapter_paths(bid)
                parent_opts = [None] + [p[0] for p in paths]
                p2path = {None: "（顶级章节）", **{i: p for i, p in paths}}
                with st.form("form_chapter"):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    cname = c1.text_input("章节名称")
                    pid = c2.selectbox("上级章节", parent_opts,
                                       format_func=lambda i: p2path[i])
                    if c3.form_submit_button("添加") and cname.strip():
                        db.add_chapter(bid, cname.strip(), pid)
                        st.rerun()

                if paths:
                    st.dataframe(pd.DataFrame(
                        [{"ID": i, "路径": p} for i, p in paths]),
                        use_container_width=True, hide_index=True)
                    del_c = st.selectbox("删除章节（级联删除子章节）",
                                         [p[0] for p in paths],
                                         format_func=lambda i: p2path[i],
                                         key="del_chap")
                    if st.button("删除章节"):
                        db.delete_chapter(del_c)
                        st.rerun()

        with tab2:
            st.subheader("数据库备份")
            st.download_button(
                "⬇️ 下载 bank.db",
                db.export_db_bytes(),
                file_name=f"bank_{datetime.now():%Y%m%d_%H%M}.db",
                mime="application/octet-stream")
            st.caption("恢复方式：把下载的 .db 文件覆盖到 `data/bank.db` 后重启应用。")

        with tab3:
            st.subheader("一键初始化高中数学示例数据")
            st.caption("会创建「人教A版必修一」及若干章节，并插入 3 道示例题。")
            if st.button("初始化示例数据"):
                db.add_book("人教A版必修一", "人民教育出版社", "高一")
                books = db.list_books()
                bid = next(b["id"] for b in books if b["name"] == "人教A版必修一")
                db.add_chapter(bid, "第一章 集合与常用逻辑用语")
                db.add_chapter(bid, "第二章 一元二次函数、方程和不等式")
                db.add_chapter(bid, "第三章 函数的概念与性质")
                chs = db.chapter_paths(bid)
                cid = chs[0][0] if chs else None

                db.add_question({
                    "book_id": bid, "chapter_id": cid, "qtype": "单选题",
                    "difficulty": 2, "score": 5,
                    "content": "已知集合 $A=\\{1,2,3\\}$，$B=\\{2,3,4\\}$，则 $A\\cap B=$（  ）",
                    "options": ["A. $\\{1,2\\}$", "B. $\\{2,3\\}$",
                                "C. $\\{3,4\\}$", "D. $\\{1,4\\}$"],
                    "answer": "B", "analysis": "两个集合的公共元素为 2 和 3。",
                    "tags": "集合,交集",
                })
                db.add_question({
                    "book_id": bid, "chapter_id": cid, "qtype": "填空题",
                    "difficulty": 3, "score": 5,
                    "content": "函数 $f(x)=\\dfrac{1}{\\sqrt{x-2}}$ 的定义域是 ______。",
                    "answer": "$(2,+\\infty)$",
                    "analysis": "需 $x-2>0$，即 $x>2$。",
                    "tags": "函数,定义域",
                })
                db.add_question({
                    "book_id": bid, "chapter_id": cid, "qtype": "解答题",
                    "difficulty": 4, "score": 12,
                    "content": "已知 $f(x)=x^2-2ax+3$ 在区间 $[1,+\\infty)$ 上单调递增，求实数 $a$ 的取值范围。",
                    "answer": "$a\\le 1$",
                    "analysis": "对称轴 $x=a$，开口向上，故 $a\\le 1$。",
                    "tags": "二次函数,单调性",
                })
                st.success("示例数据已写入")
                st.rerun()

    # ============================================================
    # 主入口
    # ============================================================
    PAGES = {
        "📝 题目录入": page_input,
        "📚 题库浏览": page_browse,
        "🎯 组卷与导出": page_paper,
        "❌ 错题追踪": page_wrong,
        "👥 学生管理": page_students,
        "⚙️ 数据与设置": page_settings,
    }

    st.sidebar.title("📐 高中数学题库")
    st.sidebar.caption(f"题库共 {db.count_questions()} 题")
    choice = st.sidebar.radio("导航", list(PAGES.keys()), label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption("Streamlit + SQLite 本地版\n数据全部保存在本机")

    PAGES[choice]()