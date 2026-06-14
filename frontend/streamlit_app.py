"""
旅小智 TripAI — Streamlit 前端
AI 聊天框模式 · 借鉴 LX_SkyRoam 设计 · Plan-Execute + ReAct 混合

运行方式:
  streamlit run frontend/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

import streamlit as st
import requests

# ======================== 页面配置 ========================
st.set_page_config(
    page_title="旅小智 · TripAI",
    page_icon="✈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")

# ======================== Session State 初始化 ========================
for key, default in [
    ("chat_messages", []),           # [{role, content, timestamp, metadata}]
    ("session_id", None),
    ("active_task_id", None),
    ("task_status", None),           # idle/processing/completed/failed
    ("accumulated_facts", {}),
    ("show_plan_result", False),
    ("plan_result", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ======================== 全局 CSS ========================
def inject_css() -> None:
    st.markdown("""
    <style>
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
        -webkit-font-smoothing: antialiased;
    }
    .stApp { background: #0f0f1e; }

    /* ── 渐变文字 ── */
    .gradient-text {
        background: linear-gradient(135deg, #6366f1, #a855f7, #06b6d4);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
    }

    /* ── 按钮 ── */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
        color: #fff !important; font-weight: 600 !important;
        border-radius: 12px !important; border: none !important;
        transition: all 0.3s; box-shadow: 0 4px 20px rgba(99,102,241,0.3);
    }
    .stButton > button:hover {
        transform: translateY(-1px); box-shadow: 0 8px 30px rgba(99,102,241,0.4) !important;
        border: none !important;
    }

    /* ── 进度条 ── */
    .stProgress > div > div { background: linear-gradient(90deg, #6366f1, #a855f7, #06b6d4); border-radius: 10px; }
    .stProgress > div { background: rgba(255,255,255,0.06); border-radius: 10px; }

    /* ── 输入框 ── */
    .stTextInput input, .stTextArea textarea {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        color: #e8e8f0 !important; border-radius: 10px !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #6366f1 !important;
        box-shadow: 0 0 0 2px rgba(99,102,241,0.2) !important;
    }
    .stSelectbox > div, .stMultiSelect > div {
        background: rgba(255,255,255,0.05) !important;
        border-color: rgba(255,255,255,0.08) !important;
        color: #e8e8f0 !important; border-radius: 10px !important;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] { gap: 0; background: transparent; }
    .stTabs [data-baseweb="tab"] {
        color: rgba(232,232,240,0.4) !important; font-weight: 500;
        border-bottom: 2px solid transparent; transition: color 0.3s, border-color 0.3s;
    }
    .stTabs [aria-selected="true"] { color: #a78bfa !important; border-bottom-color: #a78bfa !important; }

    /* ── Expander ── */
    .streamlit-expanderHeader {
        background: rgba(255,255,255,0.04) !important; border-radius: 12px !important;
        border: 1px solid rgba(255,255,255,0.06) !important; color: #e8e8f0 !important;
    }

    /* ── Metric ── */
    [data-testid="stMetricValue"] { color: #e8e8f0 !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] { color: rgba(232,232,240,0.5) !important; font-size: .75rem !important; text-transform: uppercase; letter-spacing: .06em; }

    /* ── 状态点 ── */
    .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
    .status-dot.generating { background: #f59e0b; animation: pulse 1.5s infinite; }
    .status-dot.completed { background: #10b981; }
    .status-dot.failed { background: #ef4444; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

    hr { border-color: rgba(255,255,255,0.06) !important; }

    /* ── 侧边栏（折叠用） ── */
    section[data-testid="stSidebar"] { background: #0a0a1a; border-right: 1px solid rgba(255,255,255,0.06); }
    section[data-testid="stSidebar"] * { color: #e8e8f0 !important; }
    section[data-testid="stSidebar"] .stButton > button {
        background: rgba(255,255,255,0.08) !important; color: #e8e8f0 !important;
        border: 1px solid rgba(255,255,255,0.1) !important; box-shadow: none !important;
    }
    </style>
    """, unsafe_allow_html=True)


# ======================== API 工具 ========================
def api_post(path: str, json_data: dict, timeout: int = 60) -> Optional[dict]:
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=json_data, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def api_get(path: str, timeout: int = 30) -> Optional[dict]:
    try:
        r = requests.get(f"{API_BASE_URL}{path}", timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def poll_task(task_id: str, timeout: int = 600) -> Optional[dict]:
    started = time.time()
    while time.time() - started < timeout:
        s = api_get(f"/status/{task_id}", timeout=10)
        if not s:
            time.sleep(3)
            continue
        if s.get("status") in ("completed", "failed", "cancelled"):
            return s
        time.sleep(3)
    return None


# ======================== 聊天消息渲染 ========================
def render_message(msg: dict):
    """渲染单条聊天消息气泡。"""
    role = msg.get("role", "user")
    content = msg.get("content", "")
    meta = msg.get("metadata", {}) or {}
    intent = meta.get("intent", "")
    task_id = meta.get("task_id", "")

    if role == "user":
        st.markdown(f"""
        <div style="display:flex;justify-content:flex-end;margin:0.5rem 0">
            <div style="max-width:75%;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;border-radius:16px 16px 4px 16px;padding:0.75rem 1.25rem;font-size:0.95rem;line-height:1.6;box-shadow:0 4px 16px rgba(99,102,241,0.2)">
                {content}
            </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="display:flex;justify-content:flex-start;margin:0.5rem 0">
            <div style="max-width:80%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.08);border-radius:16px 16px 16px 4px;padding:0.75rem 1.25rem;font-size:0.95rem;line-height:1.6;color:#e8e8f0">
                <div style="font-size:0.75rem;color:#a78bfa;margin-bottom:0.25rem">✦ 旅小智</div>
                {content}
            </div>
        </div>""", unsafe_allow_html=True)

        # 如果创建了计划，显示操作按钮
        if intent == "create_plan" and task_id:
            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("📊 查看计划", key=f"view_{task_id}"):
                    st.session_state.active_task_id = task_id
                    st.session_state.task_status = "polling"
                    st.rerun()
            with c2:
                st.caption(f"任务 ID: `{task_id[:8]}...`")


def render_chat_container():
    """渲染聊天消息列表。"""
    messages = st.session_state.chat_messages
    if not messages:
        # 空状态欢迎
        st.markdown("""
        <div style="text-align:center;padding:4rem 0">
            <div style="font-size:4rem;margin-bottom:1rem">✈</div>
            <h1 class="gradient-text" style="font-size:2.2rem;font-weight:700;margin-bottom:0.5rem">旅小智 TripAI</h1>
            <p style="color:rgba(232,232,240,0.4);font-size:1rem;max-width:480px;margin:0 auto;line-height:1.7">
                您的 AI 旅行规划助手<br>
                告诉我您的旅行想法，我来为您规划 ✦
            </p>
            <div style="margin-top:2rem;display:flex;justify-content:center;gap:0.75rem;flex-wrap:wrap">
                <span style="background:rgba(99,102,241,0.12);color:#a5b4fc;padding:0.4rem 1rem;border-radius:20px;font-size:0.85rem">北京 3 日游</span>
                <span style="background:rgba(99,102,241,0.12);color:#a5b4fc;padding:0.4rem 1rem;border-radius:20px;font-size:0.85rem">成都美食之旅</span>
                <span style="background:rgba(99,102,241,0.12);color:#a5b4fc;padding:0.4rem 1rem;border-radius:20px;font-size:0.85rem">上海周末游</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    for msg in messages:
        render_message(msg)


# ======================== 计划结果展示 ========================
def render_plan_result(result: dict):
    tp = result.get("travel_plan", {}) or {}
    ao = result.get("agent_outputs", {}) or {}

    dest = tp.get("destination", "未知")
    duration = tp.get("duration", 0)
    group_size = tp.get("group_size", 1)
    budget = tp.get("budget_range", "未知")
    interests = tp.get("interests", [])
    travel_dates = tp.get("travel_dates", "")

    modified = tp.get("modified_agents", [])
    unchanged = tp.get("unchanged_agents", [])

    st.markdown(f"""
    <div style="margin-bottom:1rem">
        <h2 class="gradient-text" style="font-size:1.8rem;font-weight:700;margin-bottom:.25rem">✦ {dest}</h2>
        <p style="color:rgba(232,232,240,.4);font-size:.9rem">{travel_dates}  ·  {duration} 天  ·  {group_size} 人  ·  {budget}</p>
    </div>""", unsafe_allow_html=True)

    if modified:
        st.caption(f"🔄 本次调整了: {', '.join(modified)} | 保持不变: {', '.join(unchanged)}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("行程天数", f"{duration} 天")
    c2.metric("团队人数", f"{group_size} 人")
    c3.metric("预算类型", budget)
    c4.metric("兴趣标签", f"{len(interests)} 项")

    # Agent Tabs
    agent_labels = {
        "flight_agent": "✈ 航班", "train_agent": "⊞ 铁路",
        "hotel_agent": "◈ 酒店", "attraction_agent": "◆ 景点",
        "weather_agent": "◇ 天气", "local_expert": "✦ 本地攻略",
        "budget_optimizer": "◈ 预算", "itinerary_planner": "◇ 行程",
    }
    available = {k: v for k, v in ao.items() if isinstance(v, dict) and v.get("response", "").strip()}

    if available:
        labels = [agent_labels.get(k, k) for k in available]
        items = list(available.items())
        tabs = st.tabs(labels)
        for tab, (name, output) in zip(tabs, items):
            with tab:
                if output.get("status") == "degraded":
                    st.caption("⚠ 数据已降级")
                st.markdown(output.get("response", ""))

    # 最终方案
    fp = tp.get("final_plan", "")
    if fp:
        st.markdown("---")
        st.markdown('<h3 class="gradient-text" style="font-size:1.3rem;font-weight:700">✦ 完整行程方案</h3>', unsafe_allow_html=True)
        st.markdown(fp)

    # 下载
    safe_dest = dest.replace("/", "-").replace("\\", "-")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        label="📥 下载 Markdown 报告",
        data=_build_markdown(result),
        file_name=f"{safe_dest}-{group_size}人-旅行指南-{ts}.md",
        mime="text/markdown",
    )


def _build_markdown(result: dict) -> str:
    tp = result.get("travel_plan", {}) or {}
    ao = result.get("agent_outputs", {}) or {}
    dest = tp.get("destination", "未知")

    md = f"""# {dest} 旅行规划指南

## 规划概览
| 项目 | 详情 |
|------|------|
| 目的地 | {dest} |
| 旅行日期 | {tp.get('travel_dates','')} |
| 行程天数 | {tp.get('duration',0)} 天 |
| 团队人数 | {tp.get('group_size',1)} 人 |
| 预算类型 | {tp.get('budget_range','')} |

---
"""
    names = {"flight_agent":"✈ 航班","train_agent":"⊞ 铁路","hotel_agent":"◈ 酒店","attraction_agent":"◆ 景点","weather_agent":"◇ 天气","local_expert":"✦ 本地攻略","budget_optimizer":"◈ 预算","itinerary_planner":"◇ 行程"}
    for name, output in ao.items():
        if not isinstance(output, dict): continue
        resp = output.get("response","")
        if not resp.strip(): continue
        md += f"### {names.get(name,name)}（{output.get('status','?').upper()}）\n\n{resp}\n\n---\n\n"

    fp = tp.get("final_plan","")
    if fp: md += f"## 完整行程方案\n\n{fp}\n\n---\n\n"
    md += f"""## 报告信息
- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 生成方式: 旅小智 TripAI · LangGraph 多智能体系统
---
*本报告由旅小智 TripAI 自动生成*
"""
    return md


# ======================== 主函数 ========================
def main() -> None:
    inject_css()

    # ── 侧边栏（折叠，仅放辅助功能） ──
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center;padding:.5rem 0">
            <div style="font-size:2rem;color:#a78bfa;margin-bottom:.25rem">✈</div>
            <h1 class="gradient-text" style="font-size:1.3rem;font-weight:700;margin:0">旅小智</h1>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        if st.button("🔄 新对话", use_container_width=True):
            st.session_state.chat_messages = []
            st.session_state.session_id = None
            st.session_state.active_task_id = None
            st.session_state.task_status = None
            st.session_state.accumulated_facts = {}
            st.session_state.show_plan_result = False
            st.session_state.plan_result = None
            st.rerun()

        st.caption(f"会话: `{st.session_state.session_id or '未创建'}`")

        if st.session_state.accumulated_facts:
            with st.expander("📋 已收集的信息", expanded=False):
                for k, v in st.session_state.accumulated_facts.items():
                    if v:
                        st.caption(f"**{k}**: {v}")

        # 计划修改输入
        if st.session_state.active_task_id and st.session_state.task_status == "completed":
            st.markdown("---")
            st.caption("💡 对计划不满意？在下方输入框中直接说，如：")
            st.caption("「把酒店换成300以内的」")
            st.caption("「再加一天行程」")

    # ── 主区域：聊天界面 ──
    # 聊天消息区（占 80% 高度感）
    chat_area = st.container()
    with chat_area:
        if st.session_state.show_plan_result and st.session_state.plan_result:
            # 展示计划结果
            with st.container():
                c1, c2 = st.columns([10, 1])
                with c1:
                    st.markdown("### 📊 旅行计划")
                with c2:
                    if st.button("✕", key="close_plan"):
                        st.session_state.show_plan_result = False
                        st.rerun()
            render_plan_result(st.session_state.plan_result)

            st.markdown("---")
            st.caption("💬 继续在下方输入框对话，如「换个便宜酒店」来修改计划")
        else:
            render_chat_container()

    # ── 任务轮询状态 ──
    if st.session_state.task_status == "polling" and st.session_state.active_task_id:
        tid = st.session_state.active_task_id
        with st.spinner("✦ Agent 正在协作规划..."):
            result = poll_task(tid, timeout=600)
        if result:
            st.session_state.task_status = result.get("status", "failed")
            if st.session_state.task_status == "completed":
                plan = result.get("result")
                st.session_state.plan_result = plan
                st.session_state.show_plan_result = True

                # 添加 AI 回复到聊天
                dest = (plan.get("travel_plan", {}) or {}).get("destination", "")
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": f"✦ 您的 **{dest}** 旅行计划已生成！\n\n请在下方查看完整方案。如需修改，直接告诉我即可。",
                    "timestamp": datetime.now().isoformat(),
                    "metadata": {"intent": "plan_completed", "task_id": tid},
                })
            else:
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": f"抱歉，规划过程中出现了问题：{result.get('message', '未知错误')}。请重试。",
                    "timestamp": datetime.now().isoformat(),
                    "metadata": {"intent": "plan_failed"},
                })
                st.session_state.task_status = "idle"
            st.rerun()

    # ── 底部输入框 ──
    st.markdown("<br>", unsafe_allow_html=True)
    col_input, col_send = st.columns([8, 1])
    with col_input:
        user_input = st.text_input(
            "消息",
            placeholder="输入您的旅行需求...（如：我想去杭州玩3天，预算3000）",
            key="chat_input_box",
            label_visibility="collapsed",
        )
    with col_send:
        send_clicked = st.button("发送 ✦", key="send_btn", use_container_width=True)

    # 处理发送
    if (send_clicked or user_input) and user_input.strip():
        msg = user_input.strip()

        # 添加到聊天
        st.session_state.chat_messages.append({
            "role": "user",
            "content": msg,
            "timestamp": datetime.now().isoformat(),
            "metadata": {},
        })

        # 调用后端
        with st.spinner("✦ 思考中..."):
            resp = api_post("/chat", {
                "message": msg,
                "session_id": st.session_state.session_id,
            }, timeout=30)

        if resp:
            st.session_state.session_id = resp.get("session_id")
            reply = resp.get("message", "")
            intent = resp.get("intent", "chat")
            task_id = resp.get("task_id")
            facts = resp.get("extracted_facts", {})

            # 更新累积事实
            if facts:
                st.session_state.accumulated_facts = facts

            # 添加 AI 回复
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": reply,
                "timestamp": datetime.now().isoformat(),
                "metadata": {"intent": intent, "task_id": task_id},
            })

            # 如果创建了计划，自动轮询
            if intent == "create_plan" and task_id:
                st.session_state.active_task_id = task_id
                st.session_state.task_status = "polling"
        else:
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": "抱歉，连接后端服务失败。请确保后端已启动。",
                "timestamp": datetime.now().isoformat(),
                "metadata": {"intent": "error"},
            })

        st.rerun()


if __name__ == "__main__":
    main()
