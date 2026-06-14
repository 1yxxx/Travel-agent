"""
旅小智 TripAI — Streamlit 前端
布局借鉴 LX_SkyRoam_Agent：Hero → Steps → 表单居中 → 进度条 → Tabs 预览 → 结果

运行方式:
  streamlit run frontend/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
import json
import time
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
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }

    /* ── 毛玻璃卡片 ── */
    .glass-card {
        background: rgba(255,255,255,0.06) !important;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 16px !important;
        transition: transform 0.3s, box-shadow 0.3s;
    }
    .glass-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 12px 40px rgba(99,102,241,0.15);
    }

    /* ── 表单卡片 ── */
    .form-card {
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
        border-radius: 16px !important;
        padding: 2rem !important;
    }

    /* ── 按钮 ── */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
        color: #fff !important;
        font-weight: 600 !important;
        border-radius: 12px !important;
        border: none !important;
        transition: all 0.3s;
        box-shadow: 0 4px 20px rgba(99,102,241,0.3);
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 8px 30px rgba(99,102,241,0.4) !important;
        border: none !important;
    }

    /* ── 进度条 ── */
    .stProgress > div > div {
        background: linear-gradient(90deg, #6366f1, #a855f7, #06b6d4);
        border-radius: 10px;
    }
    .stProgress > div { background: rgba(255,255,255,0.06); border-radius: 10px; }

    /* ── 输入框 ── */
    .stTextInput input, .stTextArea textarea, .stNumberInput input {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        color: #e8e8f0 !important;
        border-radius: 10px !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
        border-color: #6366f1 !important;
        box-shadow: 0 0 0 2px rgba(99,102,241,0.2) !important;
    }
    .stSelectbox > div, .stMultiSelect > div {
        background: rgba(255,255,255,0.05) !important;
        border-color: rgba(255,255,255,0.08) !important;
        color: #e8e8f0 !important;
        border-radius: 10px !important;
    }

    /* ── Expander ── */
    .streamlit-expanderHeader {
        background: rgba(255,255,255,0.04) !important;
        border-radius: 12px !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
        color: #e8e8f0 !important;
    }

    /* ── Metric ── */
    [data-testid="stMetricValue"] { color: #e8e8f0 !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] {
        color: rgba(232,232,240,0.5) !important; font-size: 0.75rem !important;
        text-transform: uppercase; letter-spacing: 0.06em;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] { gap: 0; background: transparent; }
    .stTabs [data-baseweb="tab"] {
        color: rgba(232,232,240,0.4) !important; font-weight: 500;
        border-bottom: 2px solid transparent; transition: color 0.3s, border-color 0.3s;
    }
    .stTabs [aria-selected="true"] {
        color: #a78bfa !important; border-bottom-color: #a78bfa !important;
    }

    /* ── 状态指示器 ── */
    .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
    .status-dot.generating { background: #f59e0b; animation: pulse 1.5s infinite; }
    .status-dot.completed { background: #10b981; }
    .status-dot.failed { background: #ef4444; }
    .status-dot.degraded { background: #f59e0b; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

    /* ── 步骤指示器 ── */
    .step-indicator { display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap; }
    .step-item { display: flex; align-items: center; gap: .5rem; padding: .5rem 1rem; border-radius: 8px; font-size: .85rem; color: rgba(232,232,240,.35); transition: all .3s; }
    .step-item.active { background: rgba(99,102,241,.15); color: #a78bfa; font-weight: 600; }
    .step-item.done { color: #10b981; }
    .step-num { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: .8rem; background: rgba(255,255,255,.06); color: rgba(232,232,240,.3); transition: all .3s; }
    .step-item.active .step-num { background: linear-gradient(135deg,#6366f1,#8b5cf6); color: #fff; }
    .step-item.done .step-num { background: #10b981; color: #fff; }

    /* ── 分割线 ── */
    hr { border-color: rgba(255,255,255,0.06) !important; }

    /* ── 页脚 ── */
    .footer { text-align:center;padding:3rem 0;color:rgba(232,232,240,.25);font-size:.8rem;border-top:1px solid rgba(255,255,255,.04);margin-top:4rem }
    </style>
    """, unsafe_allow_html=True)


# ======================== Hero (components.html) ========================
def render_hero() -> None:
    hero = """
    <!DOCTYPE html><html><head><meta charset="utf-8"><style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:#0f0f1e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:2rem;overflow:hidden}
    .hero{position:relative;text-align:center;max-width:800px;z-index:1}
    .hero-bg{position:absolute;inset:-100px;background:radial-gradient(ellipse 600px 400px at 50% 0%,rgba(99,102,241,0.15),transparent 70%),radial-gradient(ellipse 500px 300px at 80% 80%,rgba(168,85,247,0.1),transparent 70%),radial-gradient(ellipse 400px 300px at 20% 70%,rgba(6,182,212,0.08),transparent 70%);z-index:0}
    .hero-glow{position:absolute;border-radius:50%;filter:blur(60px);opacity:.5;z-index:0}
    .hero-glow.g1{width:300px;height:300px;background:rgba(99,102,241,.2);top:-50px;left:10%;animation:float 8s ease-in-out infinite}
    .hero-glow.g2{width:200px;height:200px;background:rgba(168,85,247,.15);bottom:-30px;right:15%;animation:float 10s ease-in-out infinite reverse}
    @keyframes float{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-30px) scale(1.05)}}
    .hero-content{position:relative;z-index:1;opacity:0;animation:fadeUp 1s .2s cubic-bezier(.16,1,.3,1) forwards}
    .hero-badge{display:inline-block;background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.25);border-radius:20px;padding:.4rem 1.2rem;font-size:.85rem;color:#a5b4fc;margin-bottom:1.5rem;letter-spacing:.03em;opacity:0;animation:fadeIn .6s .4s cubic-bezier(.16,1,.3,1) forwards}
    .hero-title{font-size:clamp(2.2rem,4.5vw,3.5rem);font-weight:800;line-height:1.2;margin-bottom:1rem;opacity:0;animation:fadeIn .6s .6s cubic-bezier(.16,1,.3,1) forwards}
    .hero-title .gradient{background:linear-gradient(135deg,#6366f1,#a855f7,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
    .hero-subtitle{font-size:1.1rem;color:rgba(232,232,240,.55);line-height:1.7;max-width:560px;margin:0 auto 2rem;opacity:0;animation:fadeIn .6s .8s cubic-bezier(.16,1,.3,1) forwards}
    .hero-stats{display:flex;justify-content:center;gap:2.5rem;flex-wrap:wrap;opacity:0;animation:fadeIn .6s 1s cubic-bezier(.16,1,.3,1) forwards}
    .hero-stat{text-align:center}
    .hero-stat-num{font-size:1.8rem;font-weight:800;color:#e8e8f0}
    .hero-stat-label{font-size:.8rem;color:rgba(232,232,240,.4);margin-top:.25rem}
    @keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
    @keyframes fadeIn{from{opacity:0}to{opacity:1}}
    @media(prefers-reduced-motion:reduce){.hero-content,.hero-badge,.hero-title,.hero-subtitle,.hero-stats{animation:none;opacity:1}.hero-glow{animation:none}}
    </style></head><body>
    <div class="hero"><div class="hero-bg"></div><div class="hero-glow g1"></div><div class="hero-glow g2"></div>
    <div class="hero-content">
        <div class="hero-badge">✦ AI 多智能体旅行规划</div>
        <h1 class="hero-title"><span class="gradient">旅小智 TripAI</span></h1>
        <p class="hero-subtitle">6 个专业 AI Agent 协同工作，从航班酒店到每日行程，<br>数分钟内为您生成专属旅行方案</p>
        <div class="hero-stats">
            <div class="hero-stat"><div class="hero-stat-num">6+</div><div class="hero-stat-label">AI Agent</div></div>
            <div class="hero-stat"><div class="hero-stat-num">4</div><div class="hero-stat-label">真实数据源</div></div>
            <div class="hero-stat"><div class="hero-stat-num">&lt;5min</div><div class="hero-stat-label">生成方案</div></div>
            <div class="hero-stat"><div class="hero-stat-num">∞</div><div class="hero-stat-label">定制可能</div></div>
        </div>
    </div></div></body></html>
    """
    st.components.v1.html(hero, height=450, scrolling=False)


# ======================== 步骤指示器 ========================
def render_steps(current_step: int, generation_status: str = "") -> None:
    """4 步骤指示器：填写需求 → AI 分析 → 生成方案 → 完成"""
    steps = [
        ("1", "填写需求"),
        ("2", "AI 分析"),
        ("3", "生成方案"),
        ("4", "完成"),
    ]

    # 根据状态推断步骤
    if generation_status == "completed":
        active_idx = 3  # 全部完成
    elif generation_status in ("generating", "processing"):
        active_idx = 2  # 正在生成
    elif current_step >= 1:
        active_idx = 1  # AI 分析
    else:
        active_idx = 0

    items = []
    for i, (num, label) in enumerate(steps):
        if i < active_idx:
            cls = "done"
        elif i == active_idx:
            cls = "active"
        else:
            cls = ""
        items.append(f'<div class="step-item {cls}"><span class="step-num">{num}</span><span>{label}</span></div>')

    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:1.25rem;margin-bottom:1.5rem">
        <div class="step-indicator">{''.join(items)}</div>
    </div>
    """, unsafe_allow_html=True)


# ======================== 状态 Alert ========================
def render_status_alert(generation_status: str, message: str = "") -> None:
    if generation_status == "generating":
        st.info("🔄 正在生成您的专属旅行方案，请稍候...")
    elif generation_status == "completed":
        st.success("✅ 方案生成完成！")
    elif generation_status == "failed":
        st.error(f"❌ 方案生成失败: {message}")
    elif generation_status == "timeout":
        st.warning("⏰ 生成时间较长，您可稍后查看历史记录")


# ======================== API 工具 ========================
def _post(path: str, json_data: dict, timeout: int = 60) -> Optional[dict]:
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=json_data, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _get(path: str, timeout: int = 30) -> Optional[dict]:
    try:
        r = requests.get(f"{API_BASE_URL}{path}", timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def create_plan(request_data: dict) -> Optional[str]:
    resp = _post("/plan", request_data, timeout=60)
    return resp.get("task_id") if resp else None


def get_status(task_id: str) -> Optional[dict]:
    return _get(f"/status/{task_id}", timeout=15)


# ======================== Landing 页 ========================
def _glass_card(title: str, desc: str, icon: str = "✦") -> str:
    return f"""<div class="glass-card" style="padding:1.75rem;text-align:center;height:100%">
        <div style="font-size:2rem;margin-bottom:.75rem">{icon}</div>
        <h3 style="color:#e8e8f0;font-weight:600;font-size:1.05rem;margin-bottom:.5rem">{title}</h3>
        <p style="color:rgba(232,232,240,.45);font-size:.88rem;line-height:1.6">{desc}</p></div>"""


def _stat_card(num: str, label: str, gradient: str) -> str:
    return f"""<div style="background:linear-gradient(135deg,{gradient});border-radius:16px;padding:1.75rem;text-align:center;height:100%">
        <div style="font-size:2rem;font-weight:800;color:#fff;margin-bottom:.25rem">{num}</div>
        <div style="font-size:.85rem;color:rgba(255,255,255,.7)">{label}</div></div>"""


def render_landing() -> None:
    st.markdown("""
    <div style="text-align:center;padding:2rem 0 1rem">
        <h2 class="gradient-text" style="font-size:2rem;font-weight:700">为什么选择旅小智</h2>
        <p style="color:rgba(232,232,240,.4);margin-top:.5rem">多 Agent 协作 · 实时数据驱动 · 专属方案定制</p>
    </div>""", unsafe_allow_html=True)

    cols = st.columns(4)
    for c, (icon, title, desc) in zip(cols, [
        ("✦", "AI 多智能体", "6 个专业 Agent 并行协作\n从航班到行程一站式覆盖"),
        ("◇", "个性化定制", "按预算/兴趣/风格生成方案\n不是千篇一律的模板"),
        ("◆", "实时数据", "高德地图 · 和风天气 · 聚合数据\n所有数据来自真实 API"),
        ("◈", "专业报告", "Markdown 格式旅行指南\n随时下载随时分享"),
    ]):
        with c:
            st.markdown(_glass_card(title, desc, icon), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    cols = st.columns(4)
    for c, (num, label, grad) in zip(cols, [
        ("6+", "AI Agent", "#6366f1, #8b5cf6"),
        ("4", "真实数据源", "#06b6d4, #3b82f6"),
        ("< 5 min", "生成方案", "#10b981, #34d399"),
        ("7×24", "全天可用", "#f59e0b, #ef4444"),
    ]):
        with c:
            st.markdown(_stat_card(num, label, grad), unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center;padding:3rem 0 1rem">
        <h2 class="gradient-text" style="font-size:2rem;font-weight:700">AI 智能体团队</h2>
    </div>""", unsafe_allow_html=True)

    cols = st.columns(3)
    for i, (icon, name, desc) in enumerate([
        ("◈", "旅行顾问", "目的地概览、景点推荐"),
        ("◇", "天气分析师", "天气预报、穿衣指南"),
        ("◆", "预算优化师", "预算分配与超支预警"),
        ("✦", "当地专家", "地道美食、隐藏玩法"),
        ("◈", "行程规划师", "每日行程、路线优化"),
        ("◇", "Supervisor", "多 Agent 调度与结果整合"),
    ]):
        with cols[i % 3]:
            st.markdown(_glass_card(name, desc, icon), unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center;padding:3rem 0 1rem">
        <h2 class="gradient-text" style="font-size:2rem;font-weight:700">三步开启</h2>
    </div>""", unsafe_allow_html=True)

    cols = st.columns(3)
    for c, (num, title, desc) in zip(cols, [
        ("1", "填写偏好", "输入目的地、日期、预算与兴趣标签"),
        ("2", "一键规划", "6 个 Agent 并行协作，数分钟内生成方案"),
        ("3", "下载报告", "Markdown 旅行指南，随时查看分享"),
    ]):
        with c:
            st.markdown(f"""<div class="glass-card" style="padding:2rem;text-align:center;height:100%">
                <div style="background:linear-gradient(135deg,#6366f1,#a855f7,#06b6d4);width:48px;height:48px;border-radius:12px;display:inline-flex;align-items:center;justify-content:center;font-size:1.5rem;font-weight:800;color:#fff;margin-bottom:1rem">{num}</div>
                <h3 style="color:#e8e8f0;font-weight:600;font-size:1.05rem;margin-bottom:.5rem">{title}</h3>
                <p style="color:rgba(232,232,240,.45);font-size:.88rem;line-height:1.6">{desc}</p></div>""", unsafe_allow_html=True)

    st.markdown("""
    <div class="glass-card" style="text-align:center;padding:2.5rem;margin:3rem 0">
        <h2 style="color:#e8e8f0;font-weight:700;font-size:1.5rem;margin-bottom:.5rem">准备好开始你的旅程了吗？</h2>
        <p style="color:rgba(232,232,240,.45);margin-bottom:0">向下滚动，填写表单，开始规划 ✦</p>
    </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div class="footer">
        <p style="font-weight:700;font-size:1.1rem;color:rgba(232,232,240,.5);margin-bottom:.5rem"><span class="gradient-text">旅小智 TripAI</span></p>
        <p>LangGraph 多智能体 · DeepSeek 大模型 · FastAPI + Streamlit</p>
        <p style="margin-top:.75rem">© 2025 旅小智 Travel AI</p>
    </div>""", unsafe_allow_html=True)


# ======================== 表单（居中双列） ========================
def render_form() -> Optional[dict]:
    """居中表单 —— 借鉴 LX_SkyRoam Row+Col 双列布局。"""
    st.markdown("""
    <div style="text-align:center;padding:1.5rem 0 .5rem">
        <h2 class="gradient-text" style="font-size:1.8rem;font-weight:700">创建您的专属旅行计划</h2>
        <p style="color:rgba(232,232,240,.4);margin-top:.25rem">请填写您的旅行需求，AI 将为您生成个性化的旅行方案</p>
    </div>
    """, unsafe_allow_html=True)

    # ── 第 1 行：出发地 / 目的地 ──
    c1, c2 = st.columns(2)
    with c1:
        departure = st.text_input("🛫 出发城市", placeholder="例: 北京（填写后启用交通 Agent）", key="dep")
    with c2:
        destination = st.text_input("🎯 目的地 *", placeholder="例: 上海、成都、杭州", key="dest")

    # ── 第 2 行：日期 / 人数 ──
    c1, c2 = st.columns(2)
    with c1:
        sub1, sub2 = st.columns(2)
        with sub1:
            start_date = st.date_input("📅 出发日期", value=date.today() + timedelta(days=1), key="sdate")
        with sub2:
            end_date = st.date_input("📅 返回日期", value=date.today() + timedelta(days=8), key="edate")
    with c2:
        group_size = st.number_input("👥 出行人数", min_value=1, max_value=20, value=2, key="gsize")

    # ── 第 3 行：预算 / 住宿 ──
    c1, c2 = st.columns(2)
    with c1:
        budget_range = st.selectbox("💰 预算范围", [
            "经济型 (300-800元/天)",
            "舒适型 (800-1500元/天)",
            "中等预算 (1500-3000元/天)",
            "高端旅行 (3000-6000元/天)",
            "奢华体验 (6000元以上/天)",
        ], key="budget")
    with c2:
        accommodation = st.selectbox("🏨 住宿偏好", [
            "经济型酒店/青旅", "商务酒店", "精品酒店",
            "民宿/客栈", "度假村", "奢华酒店",
        ], key="accom")

    # ── 第 4 行：交通 / 兴趣 ──
    c1, c2 = st.columns(2)
    with c1:
        transportation = st.selectbox("🚗 交通偏好", [
            "公共交通为主", "混合交通方式", "租车自驾",
            "包车/专车", "高铁/飞机",
        ], key="trans")
    with c2:
        interests = st.multiselect("🎨 兴趣偏好", [
            "历史文化", "美食体验", "自然风光", "艺术表演", "海滨度假",
            "购物娱乐", "运动健身", "摄影打卡", "休闲放松", "主题乐园",
            "登山徒步", "文艺创作", "品酒美食", "博物馆", "夜生活",
        ], key="interests")

    # ── 第 5 行：备注（独占一行） ──
    notes = st.text_area("📝 额外备注", placeholder="例: 不吃辣、需要无障碍设施...", height=80, key="notes")

    # ── 提交按钮 ──
    submitted = st.button("🚀 开始生成方案", type="primary", use_container_width=True)

    if submitted:
        if not destination:
            st.error("请输入目的地")
            return None
        if start_date >= end_date:
            st.error("返回日期必须晚于出发日期")
            return None

        duration = (end_date - start_date).days + 1
        return {
            "departure": departure,
            "destination": destination,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "group_size": group_size,
            "budget_range": budget_range,
            "interests": interests,
            "accommodation_preference": accommodation,
            "transportation_preference": transportation,
            "duration": duration,
            "travel_dates": f"{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}",
            "special_requirements": notes,
        }

    return None


# ======================== 结果展示 ========================
def render_result(result: dict, request_data: dict) -> None:
    travel_plan = result.get("travel_plan", {}) or {}
    agent_outputs = result.get("agent_outputs", {}) or {}
    short_term_memory = result.get("short_term_memory", {}) or {}

    destination = travel_plan.get("destination", request_data.get("destination", "未知"))
    duration = travel_plan.get("duration", request_data.get("duration", 0))
    group_size = travel_plan.get("group_size", request_data.get("group_size", 1))
    budget_range = travel_plan.get("budget_range", request_data.get("budget_range", "未知"))
    interests = travel_plan.get("interests", request_data.get("interests", []))
    travel_dates = travel_plan.get("travel_dates", "")

    st.markdown(f"""
    <div style="margin-bottom:1.5rem">
        <h2 class="gradient-text" style="font-size:2rem;font-weight:700;margin-bottom:.25rem">✦ {destination}</h2>
        <p style="color:rgba(232,232,240,.4);font-size:.9rem">{travel_dates}  ·  {duration} 天  ·  {group_size} 人  ·  {budget_range}</p>
    </div>""", unsafe_allow_html=True)

    # Agent 状态点
    agent_slots = short_term_memory.get("agent_slots", {})
    if agent_slots:
        parts = []
        for a, s in agent_slots.items():
            sts = s.get("status", "")
            if sts == "completed":
                parts.append(f'<span style="display:inline-flex;align-items:center;margin-right:1rem;font-size:.85rem;color:rgba(232,232,240,.6)"><span class="status-dot completed"></span>{a}</span>')
            elif s.get("degraded"):
                parts.append(f'<span style="display:inline-flex;align-items:center;margin-right:1rem;font-size:.85rem;color:rgba(232,232,240,.6)"><span class="status-dot degraded"></span>{a} 降级</span>')
            else:
                parts.append(f'<span style="display:inline-flex;align-items:center;margin-right:1rem;font-size:.85rem;color:rgba(232,232,240,.4)"><span class="status-dot" style="background:rgba(232,232,240,.2)"></span>{a}</span>')
        st.markdown(f'<div style="margin-bottom:1.5rem">{"".join(parts)}</div>', unsafe_allow_html=True)

    # 概览指标
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("行程天数", f"{duration} 天")
    c2.metric("团队人数", f"{group_size} 人")
    c3.metric("预算类型", budget_range)
    c4.metric("兴趣标签", f"{len(interests)} 项")
    if interests:
        st.markdown(" · ".join([f"`{i}`" for i in interests]))

    # ── Tabs：Agent 输出 ──
    agent_labels = {
        "flight_agent": "✈ 航班", "train_agent": "⊞ 铁路",
        "hotel_agent": "◈ 酒店", "attraction_agent": "◆ 景点",
        "weather_agent": "◇ 天气", "local_expert": "✦ 本地攻略",
        "budget_optimizer": "◈ 预算", "itinerary_planner": "◇ 行程",
        "travel_advisor": "✦ 旅行顾问", "weather_analyst": "◇ 天气分析",
    }
    available = {k: v for k, v in agent_outputs.items() if isinstance(v, dict) and v.get("response", "").strip()}

    if available:
        labels = [agent_labels.get(k, k) for k in available]
        items = list(available.items())
        tabs = st.tabs(labels)
        for tab, (name, output) in zip(tabs, items):
            with tab:
                if output.get("status") == "degraded":
                    st.caption("⚠ 数据已降级")
                if output.get("error"):
                    st.caption(f"原因: {output.get('error')}")
                st.markdown(output.get("response", ""))

    # 最终方案
    final_plan = travel_plan.get("final_plan", "")
    if final_plan:
        st.markdown("---")
        st.markdown('<h3 class="gradient-text" style="font-size:1.5rem;font-weight:700;margin-bottom:1rem">✦ 完整行程方案</h3>', unsafe_allow_html=True)
        st.markdown(final_plan)

    # 下载
    st.markdown("---")
    safe_dest = destination.replace("/", "-").replace("\\", "-")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_content = _build_markdown(result, request_data)
    st.download_button(
        label="📥 下载 Markdown 报告",
        data=md_content,
        file_name=f"{safe_dest}-{group_size}人-旅行指南-{ts}.md",
        mime="text/markdown",
    )


def _build_markdown(result: dict, request_data: dict) -> str:
    tp = result.get("travel_plan", {}) or {}
    ao = result.get("agent_outputs", {}) or {}
    dest = tp.get("destination", request_data.get("destination", "未知"))

    md = f"""# {dest} 旅行规划指南

## 规划概览

| 项目 | 详情 |
|------|------|
| 目的地 | {dest} |
| 旅行日期 | {tp.get('travel_dates', '')} |
| 行程天数 | {tp.get('duration', 0)} 天 |
| 团队人数 | {tp.get('group_size', 1)} 人 |
| 预算类型 | {tp.get('budget_range', '')} |
| 兴趣偏好 | {', '.join(tp.get('interests', [])) or '无'} |

---
"""
    names = {"flight_agent":"✈ 航班","train_agent":"⊞ 铁路","hotel_agent":"◈ 酒店","attraction_agent":"◆ 景点","weather_agent":"◇ 天气","local_expert":"✦ 本地攻略","budget_optimizer":"◈ 预算","itinerary_planner":"◇ 行程"}
    for name, output in ao.items():
        if not isinstance(output, dict): continue
        resp = output.get("response", "")
        if not resp.strip(): continue
        md += f"### {names.get(name, name)}（{output.get('status','?').upper()}）\n\n{resp}\n\n---\n\n"

    fp = tp.get("final_plan", "")
    if fp:
        md += f"## 完整行程方案\n\n{fp}\n\n---\n\n"

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
    render_hero()

    # ── 表单居中 ──
    request_data = render_form()

    if request_data:
        # ── 步骤 + 进度 ──
        st.markdown("<br>", unsafe_allow_html=True)
        render_steps(current_step=0)

        with st.spinner("✦ 6 个 Agent 正在协作规划您的行程..."):
            task_id = create_plan(request_data)

        if not task_id:
            st.error("创建任务失败，请检查后端服务是否运行")
            return

        st.success(f"✦ 任务已创建 · ID: `{task_id}`")

        # 更新步骤
        render_steps(current_step=1, generation_status="generating")
        render_status_alert("generating")

        progress_bar = st.progress(0, text="初始化...")
        status_placeholder = st.empty()

        generation_status = "generating"
        result = None
        started = time.time()
        timeout = 600

        while time.time() - started < timeout:
            s = get_status(task_id)
            if not s:
                time.sleep(3)
                continue

            progress = s.get("progress", 0)
            msg = s.get("message", "")
            agent = s.get("current_agent", "")
            task_status = s.get("status", "")

            progress_bar.progress(progress / 100, text=f"进度: {progress}%")
            if agent:
                status_placeholder.info(f"✦ {agent}  |  {msg}")
            elif msg:
                status_placeholder.info(f"✦ {msg}")

            if progress >= 30:
                render_steps(current_step=2, generation_status="generating")

            if task_status == "completed":
                generation_status = "completed"
                result = s.get("result")
                break
            if task_status in ("failed", "cancelled"):
                generation_status = "failed"
                break

            time.sleep(3)
        else:
            generation_status = "timeout"

        # ── 最终状态 ──
        progress_bar.empty()
        status_placeholder.empty()

        if generation_status == "completed":
            render_steps(current_step=3, generation_status="completed")
            render_status_alert("completed")
            st.balloons()

            if result:
                st.markdown("<br>", unsafe_allow_html=True)
                render_result(result, request_data)
        elif generation_status == "failed":
            render_steps(current_step=0, generation_status="failed")
            render_status_alert("failed", "请检查输入后重试")
        elif generation_status == "timeout":
            render_steps(current_step=2, generation_status="timeout")
            render_status_alert("timeout")
    else:
        # 未提交表单 → Landing
        render_landing()


if __name__ == "__main__":
    main()
