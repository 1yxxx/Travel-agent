#!/usr/bin/env python3
"""
简化版旅行规划智能体

这是一个简化版本的旅行规划系统，用于测试和调试。
当AI旅行规划智能体出现问题时，可以使用这个版本作为备选方案。
"""

import json
import sys
import os
from datetime import datetime
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI

# 添加backend目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.langgraph_config import langgraph_config as config

class SimpleTravelAgent:
    """简化版旅行规划智能体"""
    
    def __init__(self):
        """初始化智能体"""
        llm_config = config.get_llm_config()
        self.llm = ChatOpenAI(**llm_config)
    
    def run_travel_planning(self, travel_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行简化的旅行规划
        
        这个方法提供一个快速、可靠的旅行规划方案，
        避免复杂的多智能体协作可能导致的问题。
        """
        try:
            print("开始简化版旅行规划...")
            
            # 提取请求信息
            destination = travel_request.get("destination", "")
            duration = travel_request.get("duration", 3)
            budget_range = travel_request.get("budget_range", "中等预算")
            interests = travel_request.get("interests", [])
            group_size = travel_request.get("group_size", 1)
            travel_dates = travel_request.get("travel_dates", "")
            transportation_preference = travel_request.get("transportation_preference", "公共交通")
            accommodation_preference = travel_request.get("accommodation_preference", "酒店")
            
            # 构建提示词
            prompt = self._build_prompt(
                destination,
                duration,
                budget_range,
                interests,
                group_size,
                travel_dates,
                transportation_preference,
                accommodation_preference
            )
            
            print("正在生成旅行规划...")
            
            # 调用LLM生成规划
            response = self.llm.invoke(prompt)
            plan_content = response.content
            
            print("旅行规划生成完成")
            
            # 构建返回结果
            result = {
                "success": True,
                "travel_plan": {
                    "destination": destination,
                    "duration": duration,
                    "budget_range": budget_range,
                    "interests": interests,
                    "group_size": group_size,
                    "travel_dates": travel_dates,
                    "transportation_preference": transportation_preference,
                    "accommodation_preference": accommodation_preference,
                    "planning_method": "简化版AI规划",
                    "generated_at": datetime.now().isoformat(),
                    "content": plan_content
                },
                "agent_outputs": {
                    "simple_agent": {
                        "status": "completed",
                        "response": plan_content,
                        "timestamp": datetime.now().isoformat()
                    }
                },
                "total_iterations": 1,
                "planning_complete": True
            }
            
            return result
            
        except Exception as e:
            print(f"简化版规划失败: {str(e)}")
            return {
                "success": False,
                "error": f"简化版规划失败: {str(e)}",
                "travel_plan": {},
                "agent_outputs": {},
                "total_iterations": 0,
                "planning_complete": False
            }
    
    def _build_prompt(
        self,
        destination: str,
        duration: int,
        budget_range: str,
        interests: List[str],
        group_size: int,
        travel_dates: str,
        transportation_preference: str,
        accommodation_preference: str
    ) -> str:
        """构建旅行规划提示词"""
        
        interests_str = "、".join(interests) if interests else "无特殊偏好"
        
        prompt = f"""
你是一个专业的旅行规划师，请为以下需求制定详细的旅行计划：

📍 目的地: {destination}
📅 旅行时长: {duration}天
💰 预算范围: {budget_range}
👥 团队人数: {group_size}人
🎯 兴趣爱好: {interests_str}
📆 旅行日期: {travel_dates}
🚗 交通偏好: {transportation_preference}
🏨 住宿偏好: {accommodation_preference}

请提供一个详细的旅行规划，包括：

## 🌍 行程概览
- 旅行主题和特色
- 推荐的旅行节奏

## 📅 日程安排
- 每日详细行程
- 主要景点和活动
- 用餐建议

## 💰 预算估算
- 住宿费用预估
- 餐饮费用预估
- 交通费用预估
- 景点门票预估
- 总预算范围

## 🏨 住宿推荐
- 推荐住宿区域
- 住宿类型建议
- 性价比推荐

## 🚗 交通指南
- 到达方式
- 当地交通
- 交通费用

## 🍽️ 美食推荐
- 当地特色美食
- 推荐餐厅
- 用餐预算

## 📝 实用贴士
- 最佳旅行时间
- 注意事项
- 实用建议

请确保规划内容详细、实用，符合预算范围和兴趣偏好。
"""
        
        return prompt


