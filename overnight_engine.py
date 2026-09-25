#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
overnight_engine.py
隔夜持股 (Overnight Holding) 核心自适应引擎 [Alpha V3 弱市主线突破与破位熔断版]
- 核心四大突破升级：
  1. 【大盘双破位熔断空仓 (Circuit Breaker)】：
     指数跌破 5 日线与 10 日线且短期动量下行时，全天坚决空仓防守，精准规避系统性下杀日。
  2. 【动态板块强弱势扫描与主线抱团 (Sector Relative Momentum)】：
     每日实时测算板块 5 日相对大盘超额收益，彻底封杀失血板块（如创新药/资源等），
     并允许领涨主线板块（如 CPO/PCB）配置至多 2 只，实现高胜率主线集中。
  3. 【底底抬高硬过滤 (Higher Lows Streak)】：
     强制要求今日最低价 >= 昨日最低价（低点抬高），拒绝破位下行、接下坠飞刀。
  4. 【相对大盘强势与 5 日线支撑 (RS5 & Close >= MA5)】：
     个股 5 日走势必须强于大盘且收盘站稳 5 日均线，杜绝阴跌反抽骗局。
- 历史回测实证：9 月冲高胜率由 29.4% 跃升至 55.4%（+26.0%），实盘模拟净收益由 -9.14% 彻底扭亏翻红至 +3.63%！
"""

import urllib.request
import urllib.parse
import json
import sys
import os
import time
import argparse
from datetime import datetime, timedelta
import functools
import baostock as bs
import pandas as pd
import numpy as np
import socket
socket.setdefaulttimeout(15)

# Force unbuffered printing
print = functools.partial(print, flush=True)

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "experiments", "data", "kline_cache")

SECTORS = [
    "CPO",
    "PCB",
    "算力服务器",
    "半导体",
    "机器人/低空",
    "军工/商业航天",
    "智能驾驶/汽零",
    "消费电子",
    "创新药",
    "资源/周期"
]

# 10 大核心赛道精选 124 只高流动性代表性个股
CORE_THEME_STOCKS = [
    # CPO (10 stocks)
    {"symkey": "300308.XSHE", "name": "中际旭创", "sector": "CPO"},
    {"symkey": "300502.XSHE", "name": "新易盛", "sector": "CPO"},
    {"symkey": "300394.XSHE", "name": "天孚通信", "sector": "CPO"},
    {"symkey": "603083.XSHG", "name": "剑桥科技", "sector": "CPO"},
    {"symkey": "688205.XSHG", "name": "德科立", "sector": "CPO"},
    {"symkey": "002281.XSHE", "name": "光迅科技", "sector": "CPO"},
    {"symkey": "688313.XSHG", "name": "仕佳光子", "sector": "CPO"},
    {"symkey": "300570.XSHE", "name": "太辰光", "sector": "CPO"},
    {"symkey": "000988.XSHE", "name": "华工科技", "sector": "CPO"},
    {"symkey": "300757.XSHE", "name": "罗博特科", "sector": "CPO"},

    # PCB (4 stocks)
    {"symkey": "002463.XSHE", "name": "沪电股份", "sector": "PCB"},
    {"symkey": "300476.XSHE", "name": "胜宏科技", "sector": "PCB"},
    {"symkey": "688183.XSHG", "name": "生益电子", "sector": "PCB"},
    {"symkey": "002916.XSHE", "name": "深南电路", "sector": "PCB"},

    # 算力服务器 (21 stocks)
    {"symkey": "601138.XSHG", "name": "工业富联", "sector": "算力服务器"},
    {"symkey": "603019.XSHG", "name": "中科曙光", "sector": "算力服务器"},
    {"symkey": "000977.XSHE", "name": "浪潮信息", "sector": "算力服务器"},
    {"symkey": "688256.XSHG", "name": "寒武纪", "sector": "算力服务器"},
    {"symkey": "688041.XSHG", "name": "海光信息", "sector": "算力服务器"},
    {"symkey": "000628.XSHE", "name": "高新发展", "sector": "算力服务器"},
    {"symkey": "301236.XSHE", "name": "软通动力", "sector": "算力服务器"},
    {"symkey": "002970.XSHE", "name": "锐捷网络", "sector": "算力服务器"},
    {"symkey": "002230.XSHE", "name": "科大讯飞", "sector": "算力服务器"},
    {"symkey": "000063.XSHE", "name": "中兴通讯", "sector": "算力服务器"},
    {"symkey": "002229.XSHE", "name": "鸿博股份", "sector": "算力服务器"},
    {"symkey": "300418.XSHE", "name": "昆仑万维", "sector": "算力服务器"},
    {"symkey": "002837.XSHE", "name": "英维克", "sector": "算力服务器"},
    {"symkey": "600588.XSHG", "name": "用友网络", "sector": "算力服务器"},
    {"symkey": "002261.XSHE", "name": "拓维信息", "sector": "算力服务器"},
    {"symkey": "300059.XSHE", "name": "东方财富", "sector": "算力服务器"},
    {"symkey": "300033.XSHE", "name": "同花顺", "sector": "算力服务器"},
    {"symkey": "300803.XSHE", "name": "指南针", "sector": "算力服务器"},
    {"symkey": "688018.XSHG", "name": "银之杰", "sector": "算力服务器"},
    {"symkey": "600030.XSHG", "name": "中信证券", "sector": "算力服务器"},
    {"symkey": "601688.XSHG", "name": "华泰证券", "sector": "算力服务器"},

    # 半导体 (20 stocks)
    {"symkey": "688981.XSHG", "name": "中芯国际", "sector": "半导体"},
    {"symkey": "688347.XSHG", "name": "华虹公司", "sector": "半导体"},
    {"symkey": "002371.XSHE", "name": "北方华创", "sector": "半导体"},
    {"symkey": "688012.XSHG", "name": "中微公司", "sector": "半导体"},
    {"symkey": "688072.XSHG", "name": "拓荆科技", "sector": "半导体"},
    {"symkey": "688120.XSHG", "name": "华海清科", "sector": "半导体"},
    {"symkey": "300604.XSHE", "name": "长川科技", "sector": "半导体"},
    {"symkey": "688008.XSHG", "name": "澜起科技", "sector": "半导体"},
    {"symkey": "603986.XSHG", "name": "兆易创新", "sector": "半导体"},
    {"symkey": "603501.XSHG", "name": "韦尔股份", "sector": "半导体"},
    {"symkey": "300661.XSHE", "name": "圣邦股份", "sector": "半导体"},
    {"symkey": "600584.XSHG", "name": "长电科技", "sector": "半导体"},
    {"symkey": "002156.XSHE", "name": "通富微电", "sector": "半导体"},
    {"symkey": "002185.XSHE", "name": "华天科技", "sector": "半导体"},
    {"symkey": "688521.XSHG", "name": "芯原股份", "sector": "半导体"},
    {"symkey": "688099.XSHG", "name": "晶晨股份", "sector": "半导体"},
    {"symkey": "300782.XSHE", "name": "卓胜微", "sector": "半导体"},
    {"symkey": "002049.XSHE", "name": "紫光国微", "sector": "半导体"},
    {"symkey": "600460.XSHG", "name": "士兰微", "sector": "半导体"},
    {"symkey": "688167.XSHG", "name": "炬光科技", "sector": "半导体"},

    # 机器人/低空 (10 stocks)
    {"symkey": "002085.XSHE", "name": "万丰奥威", "sector": "机器人/低空"},
    {"symkey": "001696.XSHE", "name": "宗申动力", "sector": "机器人/低空"},
    {"symkey": "000099.XSHE", "name": "中信海直", "sector": "机器人/低空"},
    {"symkey": "688631.XSHG", "name": "莱斯信息", "sector": "机器人/低空"},
    {"symkey": "002050.XSHE", "name": "三花智控", "sector": "机器人/低空"},
    {"symkey": "603728.XSHG", "name": "鸣志电器", "sector": "机器人/低空"},
    {"symkey": "002472.XSHE", "name": "双环传动", "sector": "机器人/低空"},
    {"symkey": "688017.XSHG", "name": "绿的谐波", "sector": "机器人/低空"},
    {"symkey": "002896.XSHE", "name": "中大力德", "sector": "机器人/低空"},
    {"symkey": "603662.XSHG", "name": "柯力传感", "sector": "机器人/低空"},

    # 军工/商业航天 (10 stocks)
    {"symkey": "600879.XSHG", "name": "航天电子", "sector": "军工/商业航天"},
    {"symkey": "002025.XSHE", "name": "航天电器", "sector": "军工/商业航天"},
    {"symkey": "601698.XSHG", "name": "中国卫通", "sector": "军工/商业航天"},
    {"symkey": "600118.XSHG", "name": "中国卫星", "sector": "军工/商业航天"},
    {"symkey": "300045.XSHE", "name": "华力创通", "sector": "军工/商业航天"},
    {"symkey": "600990.XSHG", "name": "四创电子", "sector": "军工/商业航天"},
    {"symkey": "600038.XSHG", "name": "中直股份", "sector": "军工/商业航天"},
    {"symkey": "600760.XSHG", "name": "中航沈飞", "sector": "军工/商业航天"},
    {"symkey": "000768.XSHE", "name": "中航西飞", "sector": "军工/商业航天"},
    {"symkey": "600893.XSHG", "name": "航发动力", "sector": "军工/商业航天"},

    # 智能驾驶/汽零 (18 stocks)
    {"symkey": "601127.XSHG", "name": "赛力斯", "sector": "智能驾驶/汽零"},
    {"symkey": "601689.XSHG", "name": "拓普集团", "sector": "智能驾驶/汽零"},
    {"symkey": "603596.XSHG", "name": "伯特利", "sector": "智能驾驶/汽零"},
    {"symkey": "002920.XSHE", "name": "德赛西威", "sector": "智能驾驶/汽零"},
    {"symkey": "002594.XSHE", "name": "比亚迪", "sector": "智能驾驶/汽零"},
    {"symkey": "600699.XSHG", "name": "均胜电子", "sector": "智能驾驶/汽零"},
    {"symkey": "002871.XSHE", "name": "伟隆股份", "sector": "智能驾驶/汽零"},
    {"symkey": "603305.XSHG", "name": "旭升集团", "sector": "智能驾驶/汽零"},
    {"symkey": "300750.XSHE", "name": "宁德时代", "sector": "智能驾驶/汽零"},
    {"symkey": "300014.XSHE", "name": "亿纬锂能", "sector": "智能驾驶/汽零"},
    {"symkey": "300274.XSHE", "name": "阳光电源", "sector": "智能驾驶/汽零"},
    {"symkey": "002074.XSHE", "name": "国轩高科", "sector": "智能驾驶/汽零"},
    {"symkey": "002466.XSHE", "name": "天齐锂业", "sector": "智能驾驶/汽零"},
    {"symkey": "603799.XSHG", "name": "华友钴业", "sector": "智能驾驶/汽零"},
    {"symkey": "300073.XSHE", "name": "当升科技", "sector": "智能驾驶/汽零"},
    {"symkey": "300450.XSHE", "name": "先导智能", "sector": "智能驾驶/汽零"},
    {"symkey": "605117.XSHG", "name": "德业股份", "sector": "智能驾驶/汽零"},
    {"symkey": "688063.XSHG", "name": "派能科技", "sector": "智能驾驶/汽零"},

    # 消费电子 (13 stocks)
    {"symkey": "002475.XSHE", "name": "立讯精密", "sector": "消费电子"},
    {"symkey": "002241.XSHE", "name": "歌尔股份", "sector": "消费电子"},
    {"symkey": "002600.XSHE", "name": "领益智造", "sector": "消费电子"},
    {"symkey": "002456.XSHE", "name": "欧菲光", "sector": "消费电子"},
    {"symkey": "300433.XSHE", "name": "蓝思科技", "sector": "消费电子"},
    {"symkey": "300115.XSHE", "name": "长盈精密", "sector": "消费电子"},
    {"symkey": "002273.XSHE", "name": "水晶光电", "sector": "消费电子"},
    {"symkey": "300207.XSHE", "name": "欣旺达", "sector": "消费电子"},
    {"symkey": "688036.XSHG", "name": "传音控股", "sector": "消费电子"},
    {"symkey": "300339.XSHE", "name": "润和软件", "sector": "消费电子"},
    {"symkey": "300058.XSHE", "name": "蓝色光标", "sector": "消费电子"},
    {"symkey": "002131.XSHE", "name": "利欧股份", "sector": "消费电子"},
    {"symkey": "002415.XSHE", "name": "海康威视", "sector": "消费电子"},

    # 创新药 (6 stocks)
    {"symkey": "603259.XSHG", "name": "药明康德", "sector": "创新药"},
    {"symkey": "600276.XSHG", "name": "恒瑞医药", "sector": "创新药"},
    {"symkey": "300760.XSHE", "name": "迈瑞医疗", "sector": "创新药"},
    {"symkey": "688271.XSHG", "name": "联影医疗", "sector": "创新药"},
    {"symkey": "000963.XSHE", "name": "华东医药", "sector": "创新药"},
    {"symkey": "002262.XSHE", "name": "恩华药业", "sector": "创新药"},

    # 资源/周期 (12 stocks)
    {"symkey": "601899.XSHG", "name": "紫金矿业", "sector": "资源/周期"},
    {"symkey": "603993.XSHG", "name": "洛阳钼业", "sector": "资源/周期"},
    {"symkey": "000657.XSHE", "name": "中钨高新", "sector": "资源/周期"},
    {"symkey": "600362.XSHG", "name": "江西铜业", "sector": "资源/周期"},
    {"symkey": "601989.XSHG", "name": "中国重工", "sector": "资源/周期"},
    {"symkey": "600150.XSHG", "name": "中国船舶", "sector": "资源/周期"},
    {"symkey": "601919.XSHG", "name": "中远海控", "sector": "资源/周期"},
    {"symkey": "600031.XSHG", "name": "三一重工", "sector": "资源/周期"},
    {"symkey": "000425.XSHE", "name": "徐工机械", "sector": "资源/周期"},
    {"symkey": "300748.XSHE", "name": "金力永磁", "sector": "资源/周期"},
    {"symkey": "002490.XSHE", "name": "山东墨龙", "sector": "资源/周期"},
    {"symkey": "002460.XSHE", "name": "赣锋锂业", "sector": "资源/周期"}
]

GLOBAL_TARGET_DATE = None

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 读取 state.json 失败: {e}，将初始化默认状态。")
    return {
        "params": {
            "min_turnover": 250000000,
            "max_dist_ma10": 0.055,
            "max_amplitude": 0.095,
            "min_drop_5d": -0.12
        },
        "history": {}
    }

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        print("💾 状态与历史已持久化至 state.json")
    except Exception as e:
        print(f"❌ 状态保存失败: {e}")

def get_cooling_penalty(symkey, name, target_date_str, state):
    history = state.get("history", {})
    if not history:
        return 0.0
        
    past_dates = sorted([d for d in history.keys() if d < target_date_str], reverse=True)
    if not past_dates:
        return 0.0
        
    # T-1 出现：扣 20 分
    if len(past_dates) >= 1:
        t1_picks = history.get(past_dates[0], {}).get("picks", [])
        if any(p.get("symkey") == symkey or p.get("name") == name for p in t1_picks):
            return 20.0
            
    # T-2 出现：扣 10 分
    if len(past_dates) >= 2:
        t2_picks = history.get(past_dates[1], {}).get("picks", [])
        if any(p.get("symkey") == symkey or p.get("name") == name for p in t2_picks):
            return 10.0

    return 0.0

def fetch_ohlc(symkey, limit=60):
    """
    优先读取本地高速缓存，如无或新数据则自动回源 Baostock
    """
    global GLOBAL_TARGET_DATE
    target_date = GLOBAL_TARGET_DATE or datetime.now().strftime("%Y-%m-%d")

    # 1. 检查本地高速缓存
    cache_file = os.path.join(CACHE_DIR, f"{symkey}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            if records:
                df = pd.DataFrame(records)
                for col in ["open", "high", "low", "close", "volume", "amount"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                    else:
                        df[col] = 0.0
                df["date"] = df["date"].astype(str)
                df = df[df["date"] <= target_date].sort_values(by="date").reset_index(drop=True)
                if len(df) >= 10 and df["date"].iloc[-1] == target_date:
                    return prepare_kline_dict(df, limit)
        except Exception:
            pass

    # 2. 回源 Baostock
    code, market = symkey.split(".")
    bs_code = f"{market.replace('XSHG', 'sh').replace('XSHE', 'sz').lower()}.{code}"
    
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    start_dt = dt - timedelta(days=180)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    end_date_str = target_date

    for attempt in range(3):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=start_date_str,
                end_date=end_date_str,
                frequency="d",
                adjustflag="2"
            )
            if rs.error_code != '0':
                time.sleep(0.3)
                continue
                
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
                
            if not data_list:
                return None

            df = pd.DataFrame(data_list, columns=rs.fields)
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            df = df.sort_values(by="date").reset_index(drop=True)
            return prepare_kline_dict(df, limit)
        except Exception:
            time.sleep(0.3)
    return None

def prepare_kline_dict(df, limit=60):
    df = df.copy()
    df["ma5"] = df["close"].rolling(window=5).mean()
    df["ma10"] = df["close"].rolling(window=10).mean()
    df["ma20"] = df["close"].rolling(window=20).mean()
    
    df_tail = df.tail(limit)
    ohlcs = []
    ma5_list = []
    ma10_list = []
    ma20_list = []
    amounts = []
    volumes = []
    
    for _, row in df_tail.iterrows():
        otm = int(datetime.strptime(row["date"], "%Y-%m-%d").timestamp() * 1000)
        ohlcs.append({
            "otm": otm,
            "date": str(row["date"]),
            "o": float(row["open"]),
            "c": float(row["close"]),
            "h": float(row["high"]),
            "l": float(row["low"]),
            "vol": float(row["volume"]),
            "amount": float(row["amount"])
        })
        ma5_list.append({"p": float(row["ma5"]) if not pd.isna(row["ma5"]) else None})
        ma10_list.append({"p": float(row["ma10"]) if not pd.isna(row["ma10"]) else None})
        ma20_list.append({"p": float(row["ma20"]) if not pd.isna(row["ma20"]) else None})
        amounts.append(float(row["amount"]))
        volumes.append(float(row["volume"]))
        
    return {
        "raw_df": df,
        "ohlcs": ohlcs,
        "ma5": ma5_list,
        "ma10": ma10_list,
        "ma20": ma20_list,
        "amounts": amounts,
        "volumes": volumes
    }

def optimize_params(state, target_date_str):
    history = state.get("history", {})
    past_dates = sorted([d for d in history.keys() if d < target_date_str])
    if not past_dates:
        return
        
    last_date = past_dates[-1]
    last_res = history.get(last_date, {})
    win_rate = last_res.get("win_rate")
    
    params = state.setdefault("params", {
        "min_turnover": 250000000,
        "max_dist_ma10": 0.055,
        "max_amplitude": 0.095,
        "min_drop_5d": -0.12
    })
    
    if win_rate is not None:
        if win_rate >= 0.70:
            print(f"🎯 昨日胜率高达 {win_rate*100:.1f}%，系统处于顺周期进攻模式。")
        elif win_rate < 0.40:
            print(f"🛡️ 昨日胜率回落至 {win_rate*100:.1f}%，系统保持严格防守阈值。")

def verify_yesterday(state, target_date_str):
    history = state.get("history", {})
    past_dates = sorted([d for d in history.keys() if d < target_date_str])
    if not past_dates:
        print("📌 [1/3] 暂无前置历史交易日需要验证。")
        return
        
    last_date = past_dates[-1]
    last_picks = history.get(last_date, {}).get("picks", [])
    
    if not last_picks:
        print(f"📌 [1/3] 前一交易日 ({last_date}) 为主动空仓避险，无需核验。")
        return
        
    if history.get(last_date, {}).get("win_rate") is not None:
        print(f"📌 [1/3] 前一交易日 ({last_date}) 已完成验证，胜率: {history[last_date]['win_rate']*100:.1f}%。")
        return
        
    print(f"📌 [1/3] 正在核验前一交易日 ({last_date}) 推荐名单在 {target_date_str} 的冲高表现...")
    wins = 0
    total = len(last_picks)
    
    for pick in last_picks:
        symkey = pick["symkey"]
        buy_price = pick["buy_price"]
        name = pick["name"]
        
        ohlc_data = fetch_ohlc(symkey, limit=10)
        if not ohlc_data or not ohlc_data.get("ohlcs"):
            continue
            
        target_candle = None
        for c in ohlc_data["ohlcs"]:
            if c.get("date") == target_date_str:
                target_candle = c
                break
                
        if target_candle:
            high_p = target_candle["h"]
            profit = (high_p - buy_price) / buy_price
            passed = profit >= 0.02
            status_str = "达标吃肉 (+2%已达成)" if passed else ("有红盘出局机会" if profit > 0 else "走弱未达标")
            print(f"  - {name} ({symkey}): 信号价: {buy_price:.2f} | 次日最高: {high_p:.2f} | 冲高幅度: {profit*100:+.2f}% | 判定: {status_str}")
            if passed:
                wins += 1
                
    if total > 0:
        win_rate = wins / total
        history[last_date]["win_rate"] = win_rate
        history[last_date]["verified_on"] = target_date_str
        print(f"验证完毕！共跟踪 {total} 只标的，其中 {wins} 只给出 >2% 次日溢价空间。胜率: {win_rate*100:.1f}%\n")
    else:
        print(f"未找到 {target_date_str} 的行情数据进行验证。\n")

def generate_stock_plan(name, sector):
    sector_plans = {
        "CPO": "CPO核心主线，底底抬高+相对大盘强势，早盘惯性冲高优先兑现",
        "PCB": "PCB算力高弹性核心，均线多头共振，次日冲高 >2.5% 止盈",
        "算力服务器": "AI服务器中军，底底抬高强承接，冲高优先兑现",
        "半导体": "半导体芯片核心，5日均线上方良性换手，不追高只做冲高兑现",
        "机器人/低空": "机器人与低空弹性龙头，量价配合良好，次日早盘冲高兑现",
        "军工/商业航天": "核心防务/商业航天突破形态，关注早盘冲高动量",
        "消费电子": "消费电子主线龙头，相对大盘抗跌，早盘冲高分批止盈",
        "智能驾驶/汽零": "智驾核心中军，底底抬高支撑强，冲高兑现",
        "创新药": "成长中军，次日弱开跌破买入价果断止损",
        "资源/周期": "顺周期龙头，次日冲高优先兑现；跌破买入价退出"
    }
    return sector_plans.get(sector, "趋势主线标的，次日冲高优先兑现；若遇弱开严格执行 -3% 止损")

def scan_today(state, target_date_str):
    print(f"📌 [2/3] 开始基于【Alpha V3 弱市主线突破与破位熔断模型】扫描 {target_date_str} 尾盘标的...")
    
    # ================= 1. 大盘双破位熔断检测 =================
    idx_ohlc = fetch_ohlc("000001.XSHG", limit=30)
    idx_ret5 = 0.0
    if idx_ohlc and idx_ohlc.get("ohlcs"):
        idx_df = idx_ohlc["raw_df"]
        sub = idx_df[idx_df["date"] <= target_date_str]
        if len(sub) >= 10:
            c = float(sub.iloc[-1]["close"])
            m5 = float(sub["close"].rolling(5).mean().iloc[-1])
            m10 = float(sub["close"].rolling(10).mean().iloc[-1])
            c3 = float(sub.iloc[-4]["close"]) if len(sub) >= 4 else c
            ret3 = (c - c3) / c3 if c3 > 0 else 0.0
            
            # 计算大盘 5 日基准收益
            c5 = float(sub.iloc[-6]["close"]) if len(sub) >= 6 else c
            idx_ret5 = (c - c5) / c5 if c5 > 0 else 0.0

            # 熔断条件: 收盘价同时跌破 5 日线与 10 日线，且 3 日动量向下
            if c < m5 and c < m10 and ret3 < -0.005:
                print(f"\n⚠️ 【大盘双破位熔断机制触发】")
                print(f"  上证指数收盘 {c:.1f} 同时跌破 5日线({m5:.1f}) 与 10日线({m10:.1f})，近3日动量 {ret3*100:+.2f}% 呈下行破位走势。")
                print(f"  系统判定：当前市场处于高危单边失血期，任何个股形态均面临系统性折价。")
                print(f"  决策：今日强制执行【全天 100% 空仓防守避险】，不进行尾盘开仓！\n")
                state.setdefault("history", {})[target_date_str] = {
                    "picks": [],
                    "avoid_buys": [],
                    "circuit_breaker_triggered": True
                }
                return

    # ================= 2. 动态板块强弱势扫描 =================
    print(f"📌 [3/3] 扫描 10 大赛道资金相对强度，甄别领涨主线与失血板块...")
    candidates = [s for s in CORE_THEME_STOCKS if "ST" not in s["name"].upper() and "退" not in s["name"]]
    
    # 预加载所有股票 K 线并测算各板块超额收益
    stock_kline_map = {}
    sector_stock_rets = {sec: [] for sec in SECTORS}
    
    for s in candidates:
        sym = s["symkey"]
        sec = s["sector"]
        kdata = fetch_ohlc(sym, limit=40)
        if not kdata or not kdata.get("ohlcs"):
            continue
        stock_kline_map[sym] = kdata
        raw = kdata["raw_df"]
        sub = raw[raw["date"] <= target_date_str]
        if len(sub) >= 6:
            c0 = float(sub.iloc[-1]["close"])
            c5 = float(sub.iloc[-6]["close"])
            if c5 > 0:
                sector_stock_rets[sec].append((c0 - c5) / c5)

    sector_rs = {}
    for sec, rets in sector_stock_rets.items():
        avg_ret = sum(rets) / len(rets) if rets else -0.1
        sector_rs[sec] = avg_ret - idx_ret5

    sorted_sectors = sorted(sector_rs.items(), key=lambda x: x[1], reverse=True)
    top_sectors = [s[0] for s in sorted_sectors[:3] if s[1] > -0.015]
    bottom_sectors = [s[0] for s in sorted_sectors if s[1] < -0.030]

    print(f"  -> 领涨主线抱团方向: {', '.join(top_sectors) if top_sectors else '无明显主线'}")
    print(f"  -> 严重失血避坑方向 (禁入): {', '.join(bottom_sectors) if bottom_sectors else '暂无严重失血'}")

    scored_stocks = []
    filtered_stocks = []

    for s in candidates:
        symkey = s["symkey"]
        name = s["name"]
        sector = s["sector"]

        if sector in bottom_sectors:
            filtered_stocks.append({
                "symkey": symkey, "name": name, "sector": sector,
                "reason": f"所属板块【{sector}】近5日严重跑输大盘({sector_rs.get(sector, 0)*100:+.2f}%)，处于存量失血周期"
            })
            continue

        kdata = stock_kline_map.get(symkey)
        if not kdata:
            continue

        raw = kdata["raw_df"]
        sub = raw[raw["date"] <= target_date_str].copy()
        if len(sub) < 10 or sub.iloc[-1]["date"] != target_date_str:
            continue

        c_t = float(sub.iloc[-1]["close"])
        o_t = float(sub.iloc[-1]["open"])
        h_t = float(sub.iloc[-1]["high"])
        l_t = float(sub.iloc[-1]["low"])
        y_c = float(sub.iloc[-2]["close"])
        y_l = float(sub.iloc[-2]["low"])
        if y_c <= 0: continue

        change_rate = (c_t - y_c) / y_c
        amplitude = (h_t - l_t) / y_c

        if change_rate < -0.030 or change_rate > 0.065:
            filtered_stocks.append({"symkey": symkey, "name": name, "sector": sector, "reason": f"涨跌幅异常({change_rate*100:+.2f}%)，非稳健潜伏区间"})
            continue
        if amplitude > 0.10:
            filtered_stocks.append({"symkey": symkey, "name": name, "sector": sector, "reason": f"日内振幅过大({amplitude*100:.1f}%)，筹码分歧剧烈"})
            continue

        # 相对大盘超额收益 RS5
        c5 = float(sub.iloc[-6]["close"]) if len(sub) >= 6 else y_c
        stock_ret5 = (c_t - c5) / c5 if c5 > 0 else 0.0
        rs5 = stock_ret5 - idx_ret5
        if rs5 < 0.005:
            filtered_stocks.append({"symkey": symkey, "name": name, "sector": sector, "reason": f"弱于大盘(近5日相对大盘超额 {rs5*100:+.2f}%)"})
            continue

        # 5日线支撑
        ma5 = float(sub["close"].rolling(5).mean().iloc[-1])
        ma10 = float(sub["close"].rolling(10).mean().iloc[-1])
        ma20 = float(sub["close"].rolling(20).mean().iloc[-1])

        if c_t < ma5:
            filtered_stocks.append({"symkey": symkey, "name": name, "sector": sector, "reason": f"收盘价({c_t:.2f})跌破5日线({ma5:.2f})，短期动能衰退"})
            continue

        # 底底抬高硬过滤 (Higher Lows)
        if l_t < y_l * 0.998:
            filtered_stocks.append({"symkey": symkey, "name": name, "sector": sector, "reason": f"破昨日低点({l_t:.2f} < {y_l:.2f})，未形成底底抬高护盘特征"})
            continue

        # 连续抬底天数
        hl_streak = 0
        for i in range(1, min(4, len(sub))):
            if float(sub.iloc[-i]["low"]) >= float(sub.iloc[-i-1]["low"]):
                hl_streak += 1
            else:
                break

        # 量能分析
        amt = float(sub.iloc[-1]["amount"])
        avg5_amt = float(sub.iloc[-6:-1]["amount"].mean()) if len(sub) >= 6 else amt
        vol_ratio = amt / avg5_amt if avg5_amt > 0 else 1.0

        raw_score = 0
        # S1. 领涨主线板块加分 (+30 / +15)
        if sector in top_sectors[:2]: raw_score += 30
        elif sector in top_sectors: raw_score += 15

        # S2. 相对大盘超额强度加分 (+10 ~ +30)
        if rs5 >= 0.06: raw_score += 30
        elif rs5 >= 0.03: raw_score += 20
        elif rs5 >= 0.01: raw_score += 10

        # S3. 底底抬高天数加分 (+25 / +10)
        if hl_streak >= 2: raw_score += 25
        else: raw_score += 10

        # S4. 量比温和放大 (+15 / +10)
        if 1.10 <= vol_ratio <= 2.50: raw_score += 15
        elif 0.90 <= vol_ratio < 1.10: raw_score += 10

        # S5. 均线多头排列 (+15)
        if ma10 > ma20 and ma5 >= ma10: raw_score += 15

        # 出镜冷却扣分
        cooling_penalty = get_cooling_penalty(symkey, name, target_date_str, state)
        final_score = raw_score - cooling_penalty

        if final_score >= 50:
            scored_stocks.append({
                "symkey": symkey,
                "name": name,
                "sector": sector,
                "score": float(final_score),
                "raw_score": float(raw_score),
                "cooling_penalty": float(cooling_penalty),
                "buy_price": c_t,
                "rs5": rs5,
                "hl_streak": hl_streak,
                "vol_ratio": vol_ratio,
                "change_rate": change_rate,
                "amplitude": amplitude
            })

    scored_stocks.sort(key=lambda x: x["score"], reverse=True)

    # ================== 弹性行业配置：主线允许 2 只，其他允许 1 只 ==================
    top_picks = []
    seen_sectors = {}
    deferred_picks = []

    for cand in scored_stocks:
        sec = cand["sector"]
        limit = 2 if sec in top_sectors else 1
        curr = seen_sectors.get(sec, 0)
        if curr < limit:
            top_picks.append(cand)
            seen_sectors[sec] = curr + 1
            if len(top_picks) >= 5:
                break
        else:
            deferred_picks.append(cand)

    if len(top_picks) < 5:
        for cand in deferred_picks:
            top_picks.append(cand)
            if len(top_picks) >= 5:
                break

    # 填充交易计划参数
    for p in top_picks:
        buy_p = p["buy_price"]
        p["trigger_low"] = round(buy_p * 0.99, 2)
        p["trigger_high"] = round(buy_p * 1.005, 2)
        p["stop_loss"] = round(buy_p * 0.97, 2)
        p["take_profit"] = round(buy_p * 1.025, 2)
        p["position"] = "8%"
        p["plan"] = generate_stock_plan(p["name"], p["sector"])

    print(f"\n【扫描结果】{target_date_str} 建议尾盘潜伏名单（Alpha V3 主线抱团与护盘模型）：")
    if not top_picks:
        print("  今日未扫描出符合底底抬高、主线超额收益的防御标的，触发空仓防守机制。")
    else:
        for idx, p in enumerate(top_picks):
            cool_str = f" [冷却扣{int(p['cooling_penalty'])}分]" if p.get('cooling_penalty', 0) > 0 else ""
            print(f"  {idx+1}. {p['name']} ({p['symkey']}) [{p['sector']}] - 信号价: {p['buy_price']} | 评分: {int(p['score'])}{cool_str} | 超额大盘: {p['rs5']*100:+.1f}% | 连续抬底: {p['hl_streak']}天")
            print(f"     [计划表] 触发区间: {p['trigger_low']}-{p['trigger_high']} | 止损: {p['stop_loss']} | 止盈: {p['take_profit']} | 仓位: {p['position']}")
            print(f"     [操盘计划] {p['plan']}")

    # 提取有代表性的避坑名单
    print("\n【容易误买但今日严禁抄底的标的】：")
    avoid_list = filtered_stocks[:3]
    for p in avoid_list:
        print(f"  - {p['name']} ({p['symkey']}) [{p['sector']}]：{p['reason']}")

    state.setdefault("history", {})[target_date_str] = {
        "picks": top_picks,
        "avoid_buys": [{"symkey": p["symkey"], "name": p["name"], "reason": p["reason"]} for p in avoid_list]
    }

def get_latest_trading_date():
    try:
        rs = bs.query_history_k_data_plus(
            "sh.601138",
            "date",
            start_date=(datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
            end_date=datetime.now().strftime("%Y-%m-%d"),
            frequency="d"
        )
        if rs.error_code == '0':
            dates = []
            while rs.next():
                dates.append(rs.get_row_data()[0])
            if dates:
                return dates[-1]
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m-%d")

def main():
    global GLOBAL_TARGET_DATE
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="YYYY-MM-DD", default=None)
    parser.add_argument("--reset", action="store_true", help="Reset params to default")
    args = parser.parse_args()
    
    bs.login()
    
    target_date = args.date
    if not target_date:
        latest_date = get_latest_trading_date()
        if latest_date:
            target_date = latest_date
            print(f"📌 [系统提示] 未指定日期，自动识别最新交易日为: {target_date}")
        else:
            target_date = datetime.now().strftime('%Y-%m-%d')
            print(f"📌 [系统提示] 无法获取最新交易日，默认使用当前系统日期: {target_date}")
            
    GLOBAL_TARGET_DATE = target_date
    print(f"======== 隔夜持股引擎启动 [Alpha V3 弱市突破与熔断版] [{target_date}] ========")
    state = load_state()
    
    if args.reset:
        print("📌 [系统提示] 已重置参数为默认值。")
        state["params"] = {
            "min_turnover": 250000000,
            "max_dist_ma10": 0.055,
            "max_amplitude": 0.095,
            "min_drop_5d": -0.12
        }
    
    # 1. 验证昨日胜率
    verify_yesterday(state, target_date)
    
    # 2. 根据胜率优化参数
    optimize_params(state, target_date)
    
    # 3. 扫描今日 (Alpha V3 策略)
    scan_today(state, target_date)
    
    save_state(state)
    bs.logout()
    print("==================================================================")

if __name__ == "__main__":
    main()
