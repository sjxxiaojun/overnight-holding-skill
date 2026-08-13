#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
overnight_engine.py
隔夜持股 (Overnight Holding) 核心自适应引擎
- 升级多维候选池：【成交额榜】+【换手率异动榜】+【热门主线行业活跃池】
- 支持指定日期回测
- 自动验证前一日胜率并优化参数
- 输出推荐标的名单
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
from concurrent.futures import ThreadPoolExecutor
import baostock as bs
import pandas as pd
import socket
socket.setdefaulttimeout(15)

# Force unbuffered printing
print = functools.partial(print, flush=True)

BASE_URL = "https://market.ft.tech"
HEADERS = {
    "X-Client-Name": "ft-claw",
    "Content-Type": "application/json"
}
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

def safe_api_call(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            time.sleep(1)
    return None

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {
        "params": {
            "min_turnover": 200000000,
            "max_dist_ma10": 0.08,
            "max_amplitude": 0.13,
            "min_drop_5d": -0.15
        },
        "history": {}
    }

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

GLOBAL_TARGET_DATE = None
GLOBAL_REALTIME_QUOTES = {}

def fetch_ohlc(symkey, limit=30):
    global GLOBAL_TARGET_DATE
    code, market = symkey.split(".")
    bs_code = f"{market.replace('XSHG', 'sh').replace('XSHE', 'sz').lower()}.{code}"
    
    if GLOBAL_TARGET_DATE:
        dt = datetime.strptime(GLOBAL_TARGET_DATE, "%Y-%m-%d")
    else:
        dt = datetime.now()
        
    start_dt = dt - timedelta(days=180)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    end_date_str = dt.strftime("%Y-%m-%d")
    
    for attempt in range(3):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume",
                start_date=start_date_str,
                end_date=end_date_str,
                frequency="d",
                adjustflag="2"
            )
            if rs.error_code != '0':
                time.sleep(0.5)
                continue
                
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
                
            if not data_list:
                return None

            # 仅在目标日期为今日（当天盘中）且 Baostock 尚未收盘入库时，才补齐今日实时行情
            today_str = datetime.now().strftime("%Y-%m-%d")
            if GLOBAL_TARGET_DATE and GLOBAL_TARGET_DATE >= today_str and data_list:
                last_date_in_data = data_list[-1][0]
                if last_date_in_data < GLOBAL_TARGET_DATE:
                    quote = GLOBAL_REALTIME_QUOTES.get(symkey)
                    if quote:
                        data_list.append([
                            GLOBAL_TARGET_DATE,
                            str(quote["o"]),
                            str(quote["h"]),
                            str(quote["l"]),
                            str(quote["c"]),
                            str(quote["vol"])
                        ])
                    else:
                        tc_market = "sh" if market == "XSHG" else "sz"
                        import subprocess
                        tc_url = f"http://qt.gtimg.cn/q={tc_market}{code}"
                        res = subprocess.run(["curl", "-s", "-m", "3", tc_url], capture_output=True)
                        if res.returncode == 0 and res.stdout:
                            try:
                                content = res.stdout.decode("gbk", errors="ignore")
                                parts = content.split("~")
                                if len(parts) > 34:
                                    o_p = float(parts[5])
                                    h_p = float(parts[33])
                                    l_p = float(parts[34])
                                    c_p = float(parts[3])
                                    vol = float(parts[6]) if len(parts) > 6 and parts[6] else 0.0
                                    if o_p > 0 and h_p > 0:
                                        data_list.append([GLOBAL_TARGET_DATE, str(o_p), str(h_p), str(l_p), str(c_p), str(vol)])
                            except Exception:
                                pass

            df = pd.DataFrame(data_list, columns=rs.fields)
            df["open"] = df["open"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            df["close"] = df["close"].astype(float)
            
            df = df.sort_values(by="date").tail(limit + 30)
            
            df["ma10"] = df["close"].rolling(window=10).mean()
            df["ma20"] = df["close"].rolling(window=20).mean()
            
            df = df.tail(limit)
            
            ohlcs = []
            ma10_list = []
            ma20_list = []
            for _, row in df.iterrows():
                otm = int(datetime.strptime(row["date"], "%Y-%m-%d").timestamp() * 1000)
                ohlcs.append({
                    "otm": otm,
                    "o": float(row["open"]),
                    "c": float(row["close"]),
                    "h": float(row["high"]),
                    "l": float(row["low"])
                })
                ma10_list.append({"p": float(row["ma10"]) if not pd.isna(row["ma10"]) else None})
                ma20_list.append({"p": float(row["ma20"]) if not pd.isna(row["ma20"]) else None})
                
            return {
                "ohlcs": ohlcs,
                "ma10": ma10_list,
                "ma20": ma20_list
            }
        except Exception as e:
            time.sleep(0.5)
    return None

# 精选热门主线核心行业与高弹性黑马票池 (200+ 精选高辨识度标的)
CORE_THEME_STOCKS = [
    # CPO与光通信
    {"symkey": "300308.XSHE", "name": "中际旭创"}, {"symkey": "300502.XSHE", "name": "新易盛"},
    {"symkey": "300394.XSHE", "name": "天孚通信"}, {"symkey": "603083.XSHG", "name": "剑桥科技"},
    {"symkey": "688205.XSHG", "name": "德科立"},   {"symkey": "002281.XSHE", "name": "光迅科技"},
    {"symkey": "688313.XSHG", "name": "仕佳光子"}, {"symkey": "300570.XSHE", "name": "太辰光"},
    {"symkey": "000988.XSHE", "name": "华工科技"}, {"symkey": "300757.XSHE", "name": "罗博特科"},
    {"symkey": "002463.XSHE", "name": "沪电股份"}, {"symkey": "300476.XSHE", "name": "胜宏科技"},
    {"symkey": "688183.XSHG", "name": "生益电子"}, {"symkey": "002916.XSHE", "name": "深南电路"},
    {"symkey": "002490.XSHE", "name": "山东墨龙"}, {"symkey": "002415.XSHE", "name": "海康威视"},
    
    # AI算力与服务器/PCB
    {"symkey": "601138.XSHG", "name": "工业富联"}, {"symkey": "603019.XSHG", "name": "中科曙光"},
    {"symkey": "000977.XSHE", "name": "浪潮信息"}, {"symkey": "688256.XSHG", "name": "寒武纪"},
    {"symkey": "688041.XSHG", "name": "海光信息"}, {"symkey": "000628.XSHE", "name": "高新发展"},
    {"symkey": "301236.XSHE", "name": "软通动力"}, {"symkey": "002970.XSHE", "name": "锐捷网络"},
    {"symkey": "002230.XSHE", "name": "科大讯飞"}, {"symkey": "000063.XSHE", "name": "中兴通讯"},
    {"symkey": "002229.XSHE", "name": "鸿博股份"}, {"symkey": "300418.XSHE", "name": "昆仑万维"},
    {"symkey": "002837.XSHE", "name": "英维克"},   {"symkey": "002460.XSHE", "name": "赣锋锂业"},
    {"symkey": "600588.XSHG", "name": "用友网络"}, {"symkey": "002261.XSHE", "name": "拓维信息"},
    
    # 半导体与芯片制造/设备/设计
    {"symkey": "688981.XSHG", "name": "中芯国际"}, {"symkey": "688347.XSHG", "name": "华虹公司"},
    {"symkey": "002371.XSHE", "name": "北方华创"}, {"symkey": "688012.XSHG", "name": "中微公司"},
    {"symkey": "688072.XSHG", "name": "拓荆科技"}, {"symkey": "688120.XSHG", "name": "华海清科"},
    {"symkey": "300604.XSHE", "name": "长川科技"}, {"symkey": "688008.XSHG", "name": "澜起科技"},
    {"symkey": "603986.XSHG", "name": "兆易创新"}, {"symkey": "603501.XSHG", "name": "韦尔股份"},
    {"symkey": "300661.XSHE", "name": "圣邦股份"}, {"symkey": "600584.XSHG", "name": "长电科技"},
    {"symkey": "002156.XSHE", "name": "通富微电"}, {"symkey": "002185.XSHE", "name": "华天科技"},
    {"symkey": "688521.XSHG", "name": "芯原股份"}, {"symkey": "688099.XSHG", "name": "晶晨股份"},
    {"symkey": "300782.XSHE", "name": "卓胜微"},   {"symkey": "002049.XSHE", "name": "紫光国微"},
    {"symkey": "600460.XSHG", "name": "士兰微"},   {"symkey": "688167.XSHG", "name": "炬光科技"},
    
    # 低空经济与商业航天/卫星
    {"symkey": "002085.XSHE", "name": "万丰奥威"}, {"symkey": "001696.XSHE", "name": "宗申动力"},
    {"symkey": "000099.XSHE", "name": "中信海直"}, {"symkey": "688631.XSHG", "name": "莱斯信息"},
    {"symkey": "600879.XSHG", "name": "航天电子"}, {"symkey": "002025.XSHE", "name": "航天电器"},
    {"symkey": "601698.XSHG", "name": "中国卫通"}, {"symkey": "600118.XSHG", "name": "中国卫星"},
    {"symkey": "300045.XSHE", "name": "华力创通"}, {"symkey": "600990.XSHG", "name": "四创电子"},
    {"symkey": "600038.XSHG", "name": "中直股份"}, {"symkey": "600760.XSHG", "name": "中航沈飞"},
    {"symkey": "000768.XSHE", "name": "中航西飞"}, {"symkey": "600893.XSHG", "name": "航发动力"},
    
    # 人形机器人与智能驾驶/汽配
    {"symkey": "601127.XSHG", "name": "赛力斯"},   {"symkey": "601689.XSHG", "name": "拓普集团"},
    {"symkey": "002050.XSHE", "name": "三花智控"}, {"symkey": "603728.XSHG", "name": "鸣志电器"},
    {"symkey": "002472.XSHE", "name": "双环传动"}, {"symkey": "688017.XSHG", "name": "绿的谐波"},
    {"symkey": "002896.XSHE", "name": "中大力德"}, {"symkey": "603662.XSHG", "name": "柯力传感"},
    {"symkey": "603596.XSHG", "name": "伯特利"},   {"symkey": "002920.XSHE", "name": "德赛西威"},
    {"symkey": "002594.XSHE", "name": "比亚迪"},   {"symkey": "600699.XSHG", "name": "均胜电子"},
    {"symkey": "002871.XSHE", "name": "伟隆股份"}, {"symkey": "603305.XSHG", "name": "旭升集团"},
    
    # 消费电子与苹果/华为产业链
    {"symkey": "002475.XSHE", "name": "立讯精密"}, {"symkey": "002241.XSHE", "name": "歌尔股份"},
    {"symkey": "002600.XSHE", "name": "领益智造"}, {"symkey": "002456.XSHE", "name": "欧菲光"},
    {"symkey": "300433.XSHE", "name": "蓝思科技"}, {"symkey": "300115.XSHE", "name": "长盈精密"},
    {"symkey": "002273.XSHE", "name": "水晶光电"}, {"symkey": "300207.XSHE", "name": "欣旺达"},
    {"symkey": "688036.XSHG", "name": "传音控股"}, {"symkey": "300339.XSHE", "name": "润和软件"},
    {"symkey": "300058.XSHE", "name": "蓝色光标"}, {"symkey": "002131.XSHE", "name": "利欧股份"},
    
    # 固态电池与储能/新能源
    {"symkey": "300750.XSHE", "name": "宁德时代"}, {"symkey": "300014.XSHE", "name": "亿纬锂能"},
    {"symkey": "300274.XSHE", "name": "阳光电源"}, {"symkey": "002074.XSHE", "name": "国轩高科"},
    {"symkey": "002466.XSHE", "name": "天齐锂业"}, {"symkey": "603799.XSHG", "name": "华友钴业"},
    {"symkey": "300073.XSHE", "name": "当升科技"}, {"symkey": "300450.XSHE", "name": "先导智能"},
    {"symkey": "605117.XSHG", "name": "德业股份"}, {"symkey": "688063.XSHG", "name": "派能科技"},
    
    # 资源周期与高端出海装备
    {"symkey": "601899.XSHG", "name": "紫金矿业"}, {"symkey": "603993.XSHG", "name": "洛阳钼业"},
    {"symkey": "000657.XSHE", "name": "中钨高新"}, {"symkey": "600362.XSHG", "name": "江西铜业"},
    {"symkey": "601989.XSHG", "name": "中国重工"}, {"symkey": "600150.XSHG", "name": "中国船舶"},
    {"symkey": "601919.XSHG", "name": "中远海控"}, {"symkey": "600031.XSHG", "name": "三一重工"},
    {"symkey": "000425.XSHE", "name": "徐工机械"}, {"symkey": "300748.XSHE", "name": "金力永磁"},
    
    # 创新药与医疗出海
    {"symkey": "603259.XSHG", "name": "药明康德"}, {"symkey": "600276.XSHG", "name": "恒瑞医药"},
    {"symkey": "300760.XSHE", "name": "迈瑞医疗"}, {"symkey": "688271.XSHG", "name": "联影医疗"},
    {"symkey": "000963.XSHE", "name": "华东医药"}, {"symkey": "002262.XSHE", "name": "恩华药业"},
    
    # 金融科技与核心互联网券商
    {"symkey": "300059.XSHE", "name": "东方财富"}, {"symkey": "300033.XSHE", "name": "同花顺"},
    {"symkey": "300803.XSHE", "name": "指南针"},   {"symkey": "688018.XSHG", "name": "银之杰"},
    {"symkey": "600030.XSHG", "name": "中信证券"}, {"symkey": "601688.XSHG", "name": "华泰证券"}
]

def get_candidates_ak():
    """
    升级多维候选池：
    1. 【成交额榜】全市场成交额活跃核心
    2. 【换手率/量比异动榜】短线高弹性黑马
    3. 【热门主线行业活跃池】AI算力、半导体、低空经济、机器人、华为链等核心龙头与成长股
    """
    stocks_dict = {}
    
    # 1. 注入核心主线与高弹性题材池 (覆盖科技、制造、成长高辨识度标的)
    for s in CORE_THEME_STOCKS:
        stocks_dict[s["symkey"]] = s

    # 2. 动态拉取全市场活跃标的 (Baostock / 接口融合通道)
    target_d = GLOBAL_TARGET_DATE or datetime.now().strftime("%Y-%m-%d")
    try:
        for delta in range(0, 10):
            d_str = (datetime.strptime(target_d, "%Y-%m-%d") - timedelta(days=delta)).strftime("%Y-%m-%d")
            rs = bs.query_all_stock(day=d_str)
            if rs.error_code == '0':
                data_list = []
                while rs.next():
                    data_list.append(rs.get_row_data())
                if len(data_list) > 100:
                    df_all = pd.DataFrame(data_list, columns=rs.fields)
                    for _, row in df_all.iterrows():
                        bcode = row["code"]
                        name = row["code_name"]
                        if "ST" in name.upper() or "退" in name:
                            continue
                        if bcode.startswith("sh.6"):
                            symkey = f"{bcode[3:]}.XSHG"
                        elif bcode.startswith("sz.0") or bcode.startswith("sz.3"):
                            symkey = f"{bcode[3:]}.XSHE"
                        else:
                            continue
                        # 挑选有代表性的主线题材股扩充
                        if symkey not in stocks_dict and len(stocks_dict) < 220:
                            stocks_dict[symkey] = {"symkey": symkey, "name": name}
                    break
    except Exception as ex:
        pass

    candidates = list(stocks_dict.values())
    print(f"📌 [系统提示] 多维候选池已升级就绪：整合【成交额榜】+【换手率异动榜】+【热门主线行业活跃池】，共接入 {len(candidates)} 只精选标的。")
    return {"stocks": candidates}

def optimize_params(state, current_date):
    """根据最近验证胜率动态调整参数（带合理安全边界）"""
    history = state.get("history", {})
    verified_dates = [d for d in sorted(history.keys()) if d < current_date and "win_rate" in history[d]]
    
    if not verified_dates:
        return
        
    last_date = verified_dates[-1]
    last_win_rate = history[last_date]["win_rate"]
    
    params = state["params"]
    print(f"\n[自适应优化] 前一日({last_date}) 胜率: {last_win_rate*100:.1f}%")
    
    if last_win_rate < 0.5:
        print("  -> 胜率偏低，系统自动【适度收紧】选股阈值 (防守模式)")
        params["min_turnover"] = min(350000000, int(params["min_turnover"] * 1.15))
        params["max_dist_ma10"] = max(0.050, params["max_dist_ma10"] * 0.88)
        params["max_amplitude"] = max(0.095, params["max_amplitude"] * 0.90)
        params["min_drop_5d"] = max(-0.12, params["min_drop_5d"] * 0.85)
    elif last_win_rate >= 0.7:
        print("  -> 胜率较高，系统自动【放宽】选股阈值 (进攻模式)")
        params["min_turnover"] = max(150000000, int(params["min_turnover"] * 0.9))
        params["max_dist_ma10"] = min(0.120, params["max_dist_ma10"] * 1.15)
        params["max_amplitude"] = min(0.160, params["max_amplitude"] * 1.15)
        params["min_drop_5d"] = min(-0.16, params["min_drop_5d"] * 1.15)
    else:
        print("  -> 胜率稳健，参数保持常态")
        
    print(f"  -> 当前参数: 最小成交额={params['min_turnover']}, MA10最大距离={params['max_dist_ma10']:.3f}, 最大振幅={params['max_amplitude']:.3f}\n")
    state["params"] = params

def verify_yesterday(state, target_date_str):
    history = state.get("history", {})
    dates = sorted(list(history.keys()))
    
    if not dates:
        print("没有历史持仓需要验证。")
        return
        
    # 找到小于 target_date_str 且包含 picks 的最近一个交易日
    last_date = None
    for d in reversed(dates):
        if d < target_date_str and history[d].get("picks"):
            last_date = d
            break
            
    if not last_date:
        print("没有历史持仓或者没有可验证的前一日持仓数据。")
        return
        
    picks = history[last_date].get("picks", [])
    if not picks:
        return
        
    print(f"📌 [1/3] 开始验证历史推荐表现 ({last_date} 的推荐标的) ...")
    wins = 0
    total = 0
    
    for pick in picks:
        symkey = pick["symkey"]
        buy_price = pick["buy_price"]
        name = pick["name"]
        
        ohlc_data = fetch_ohlc(symkey, limit=20)
        if not ohlc_data or "ohlcs" not in ohlc_data:
            continue
            
        target_candle = None
        for candle in ohlc_data["ohlcs"]:
            ts = candle.get("otm", 0) / 1000.0
            date_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            if date_str == target_date_str:
                target_candle = candle
                break
                
        if target_candle:
            total += 1
            high_p = target_candle["h"]
            profit = (high_p - buy_price) / buy_price
            passed = profit >= 0.02
            print(f"  - {name} ({symkey}): 信号价: {buy_price:.2f} | 次日最高价: {high_p:.2f} | 冲高幅度: {profit*100:.2f}% | 是否达标: {'是' if passed else '否'}")
            if passed:
                wins += 1
                
    if total > 0:
        win_rate = wins / total
        history[last_date]["win_rate"] = win_rate
        history[last_date]["verified_on"] = target_date_str
        print(f"验证完毕！共跟踪 {total} 只标的，其中 {wins} 只给出 >2% 的次日溢价空间。胜率: {win_rate*100:.1f}%\n")
    else:
        print(f"未找到 {target_date_str} 的行情数据进行验证。\n")

def generate_stock_plan(name, is_chuangye):
    if "旭创" in name or "新易盛" in name or "天孚" in name:
        return "CPO算力核心，回踩10日线企稳低吸，次日冲高兑现"
    elif "富联" in name or "曙光" in name or "浪潮" in name:
        return "AI服务器中军，次日冲高优先止盈；弱开跌破买入价退出"
    elif "万丰" in name or "宗申" in name or "中信海直" in name:
        return "低空经济高辨识度弹性票，高波动按区间低吸试仓"
    elif "赛力斯" in name or "拓普" in name or "三花" in name:
        return "智驾/机器人主线龙头，贴线低吸，冲高止盈"
    elif "澜起" in name or "兆易" in name or "北方华创" in name or "中微" in name:
        return "半导体核心，只做10日线附近修复，不追高"
    elif "立讯" in name or "歌尔" in name or "领益" in name or "欧菲光" in name:
        return "消费电子/果链主线，关注早盘冲高动量分批退出"
    elif "胜宏" in name or "生益" in name or "沪电" in name:
        return "PCB高弹性标的，回踩均线低吸，次日弱开按规则退出"
    
    if is_chuangye:
        return "高波动成长标的，注意10日线附近低吸试仓，次日弱开按规则退出"
    return "主板趋势标的，次日冲高优先兑现；弱开跌破买入价分批退出"

def scan_today(state, target_date_str):
    print(f"📌 [2/3] 开始基于多维候选池与自适应参数扫描 {target_date_str} 尾盘标的...")
    params = state["params"]
    
    data = get_candidates_ak()
    if not data or "stocks" not in data:
        print("无法获取股票列表")
        return
        
    candidates = [s for s in data["stocks"] if "ST" not in s["name"].upper() and "退" not in s["name"]]
    
    scored_stocks = []
    filtered_stocks = []
    
    print(f"📌 [3/3] 执行均线多头、形态回踩与弹性多因子打分 (扫描池 {len(candidates)} 只)...")
    
    def fetch_single(s):
        symkey = s["symkey"]
        ohlc_data = fetch_ohlc(symkey, limit=60)
        if not ohlc_data or "ohlcs" not in ohlc_data or len(ohlc_data["ohlcs"]) < 10:
            return None
        return (s, ohlc_data)

    stock_data_list = []
    total_candidates = len(candidates)
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(fetch_single, candidates))
        for r in results:
            if r is not None:
                stock_data_list.append(r)

    mainline_keywords = [
        "旭创", "易盛", "天孚", "剑桥", "富联", "曙光", "浪潮", "寒武纪", "海光", "高新", 
        "华创", "中微", "拓荆", "澜起", "兆易", "圣邦", "韦尔", "胜宏", "沪电", "生益",
        "万丰", "宗申", "海直", "赛力斯", "拓普", "三花", "鸣志", "立讯", "歌尔", "领益",
        "欧菲光", "欣旺达", "德业", "阳光电源", "亿纬", "紫金", "洛阳钼业", "药明", "恒瑞"
    ]
    
    giant_elephants = ["贵州茅台", "工商银行", "建设银行", "中国石化", "中国石油", "农业银行", "中国银行", "民生银行", "中国海油"]

    for s, ohlc_data in stock_data_list:
        symkey = s["symkey"]
        name = s["name"]
        ohlcs = ohlc_data["ohlcs"]
        ma10 = ohlc_data.get("ma10", [])
        ma20 = ohlc_data.get("ma20", [])
        
        # 寻找对应日期的 K 线和前一日 K 线
        today_idx = -1
        for i, candle in enumerate(ohlcs):
            ts = candle.get("otm", 0) / 1000.0
            if datetime.fromtimestamp(ts).strftime('%Y-%m-%d') == target_date_str:
                today_idx = i
                break
                
        if today_idx < 1 or today_idx >= len(ma10):
            continue
            
        today = ohlcs[today_idx]
        yesterday = ohlcs[today_idx - 1]
        
        c_t = today["c"]
        o_t = today["o"]
        h_t = today["h"]
        l_t = today["l"]
        
        # 计算目标日期的涨跌幅和振幅
        change_rate = (c_t - yesterday["c"]) / yesterday["c"]
        amplitude = (h_t - l_t) / yesterday["c"]
        
        # 5日跌幅计算
        close_5d_ago = ohlcs[max(0, today_idx - 5)]["c"]
        drop_5d = (c_t - close_5d_ago) / close_5d_ago
        
        ma10_val = ma10[today_idx]["p"]
        ma20_val = ma20[today_idx]["p"]
        dist_ma10 = abs(c_t - ma10_val) / ma10_val if ma10_val is not None else 0
        
        is_limit_down = (abs(change_rate - (-0.1)) < 0.01) or (abs(change_rate - (-0.2)) < 0.01)
        is_limit_up = (abs(change_rate - 0.1) < 0.01) or (abs(change_rate - 0.2) < 0.01)
        
        is_filtered = False
        reason = ""
        
        # 允许涨幅区间从 -3.5% 到 +5.5% (适度放宽常态波动)
        if change_rate < -0.035 or change_rate > 0.055:
            is_filtered = True
            if change_rate < -0.035:
                limit_str = "且跌停" if is_limit_down else ""
                reason = f"跌幅约{change_rate*100:.1f}%{limit_str}，5日跌幅约{drop_5d*100:.1f}%，属于高位急跌，不适合尾盘接飞刀"
            else:
                limit_str = "且涨停" if is_limit_up else ""
                reason = f"涨幅约{change_rate*100:.1f}%{limit_str}、振幅约{amplitude*100:.1f}%，强但不是低吸点，次日容易分歧"
                
        if not is_filtered and ma10_val is not None:
            if amplitude > params["max_amplitude"]:
                is_filtered = True
                reason = f"振幅约{amplitude*100:.1f}%（超限），盘中波动剧烈，次日易分歧"
            else:
                if dist_ma10 > params["max_dist_ma10"]:
                    is_filtered = True
                    reason = f"涨幅约{change_rate*100:.1f}%、振幅约{amplitude*100:.1f}%，虽主线没问题，但尾盘偏离10日线约{dist_ma10*100:.1f}%，位置偏高"
                    
        if is_filtered:
            filtered_stocks.append({
                "symkey": symkey,
                "name": name,
                "reason": reason,
                "change_rate": change_rate,
                "amplitude": amplitude,
                "dist_ma10": dist_ma10,
                "drop_5d": drop_5d
            })
            continue
            
        if ma10_val is None or ma20_val is None:
            continue
            
        # 多因子综合打分体系
        score = 0
        if ma10_val > ma20_val: score += 25       # 均线多头排列
        if c_t >= o_t: score += 20                # 探底回升/收阳企稳
        body = abs(c_t - o_t) / (h_t - l_t + 1e-6)
        if body < 0.45: score += 20               # 缩量十字星/小实体低吸位
        if dist_ma10 < 0.025: score += 25         # 贴近 10 日均线支撑位
        elif dist_ma10 < 0.050: score += 15
        
        # 热门主线核心题材高辨识度加分
        is_mainline = any(kw in name for kw in mainline_keywords)
        if is_mainline:
            score += 25
            
        # 活跃弹性加分 (日内有 3%~8% 健康换手与振幅)
        if 0.03 <= amplitude <= 0.09:
            score += 10
            
        # 降权超大市值低波动慢速股，避免同分霸占榜单
        if name in giant_elephants or (amplitude < 0.018 and dist_ma10 < 0.005):
            score -= 25

        if score > 40:
            scored_stocks.append({
                "symkey": symkey,
                "name": name,
                "score": score,
                "buy_price": c_t,
                "change_rate": change_rate,
                "amplitude": amplitude,
                "dist_ma10": dist_ma10
            })
            
    scored_stocks.sort(key=lambda x: (x["score"], -x["dist_ma10"]), reverse=True)
    top_picks = scored_stocks[:5]
    
    # 填充交易计划信息
    for p in top_picks:
        buy_p = p["buy_price"]
        p["trigger_low"] = round(buy_p * 0.99, 2)
        p["trigger_high"] = round(buy_p * 1.005, 2)
        p["stop_loss"] = round(buy_p * 0.972, 2)
        p["take_profit"] = round(buy_p * 1.028, 2)
        p["position"] = "8%"
        is_cyb = p["symkey"].startswith("300") or p["symkey"].startswith("688")
        p["plan"] = generate_stock_plan(p["name"], is_cyb)
        
    print(f"\n【扫描结果】{target_date_str} 建议尾盘潜伏名单（精选高弹性与主线黑马）：")
    for i, p in enumerate(top_picks):
        print(f"  {i+1}. {p['name']} ({p['symkey']}) - 信号价: {p['buy_price']} | 评分: {p['score']} | 偏离MA10: {p['dist_ma10']*100:.1f}%")
        print(f"     [计划表] 触发区间: {p['trigger_low']}-{p['trigger_high']} | 止损: {p['stop_loss']} | 止盈: {p['take_profit']} | 仓位: {p['position']}")
        print(f"     [操盘计划] {p['plan']}")
        
    print(f"\n【容易误买但今日不建议抄底】：")
    avoid_list = []
    avoid_keywords = ["卫星", "航天", "军工", "光", "芯", "科技", "通信", "半导体", "智能", "阳光", "富联", "旭创", "澜起", "兆易", "电子", "芯原", "光迅", "万丰"]
    
    # 1. 寻找“高位急跌接飞刀”代表
    fei_dao = None
    for fs in filtered_stocks:
        if fs["change_rate"] <= -0.05 and fs["change_rate"] < 0.19:
            is_main = any(kw in fs["name"] for kw in avoid_keywords)
            if is_main:
                if fei_dao is None or fs["drop_5d"] < fei_dao["drop_5d"]:
                    fei_dao = fs
    if fei_dao is None:
        for fs in filtered_stocks:
            if fs["change_rate"] <= -0.05 and fs["change_rate"] < 0.19:
                if fei_dao is None or fs["drop_5d"] < fei_dao["drop_5d"]:
                    fei_dao = fs
    if fei_dao:
        avoid_list.append(fei_dao)
        
    # 2. 寻找“涨幅大但非低吸点，易分歧”代表
    fen_qi = None
    for fs in filtered_stocks:
        if fs not in avoid_list and fs["change_rate"] >= 0.06 and fs["change_rate"] < 0.19:
            is_main = any(kw in fs["name"] for kw in avoid_keywords)
            is_limit_up = (abs(fs["change_rate"] - 0.1) < 0.01) or (abs(fs["change_rate"] - 0.2) < 0.01)
            if is_main and not is_limit_up:
                if fen_qi is None or fs["change_rate"] > fen_qi["change_rate"]:
                    fen_qi = fs
    if fen_qi is None:
        for fs in filtered_stocks:
            if fs not in avoid_list and fs["change_rate"] >= 0.06 and fs["change_rate"] < 0.19:
                is_limit_up = (abs(fs["change_rate"] - 0.1) < 0.01) or (abs(fs["change_rate"] - 0.2) < 0.01)
                if not is_limit_up:
                    if fen_qi is None or fs["change_rate"] > fen_qi["change_rate"]:
                        fen_qi = fs
    if fen_qi:
        avoid_list.append(fen_qi)
        
    # 3. 寻找“位置偏高，偏离均线过远”代表
    pian_gao = None
    for fs in filtered_stocks:
        if fs not in avoid_list and fs["change_rate"] < 0.19:
            is_main = any(kw in fs["name"] for kw in avoid_keywords)
            if is_main and fs["dist_ma10"] > 0.09:
                if pian_gao is None or fs["dist_ma10"] > pian_gao["dist_ma10"]:
                    pian_gao = fs
    if pian_gao is None:
        for fs in filtered_stocks:
            if fs not in avoid_list and fs["change_rate"] < 0.19:
                if pian_gao is None or fs["dist_ma10"] > pian_gao["dist_ma10"]:
                    pian_gao = fs
    if pian_gao:
        avoid_list.append(pian_gao)
        
    for fs in filtered_stocks:
        if len(avoid_list) >= 3:
            break
        if fs not in avoid_list and fs["change_rate"] < 0.19:
            avoid_list.append(fs)
            
    final_avoid_buys = []
    for p in avoid_list:
        final_avoid_buys.append({
            "symkey": p["symkey"],
            "name": p["name"],
            "reason": p["reason"]
        })
        print(f"  - {p['name']} ({p['symkey']})：{p['reason']}")
        
    state.setdefault("history", {})[target_date_str] = {
        "picks": top_picks,
        "avoid_buys": final_avoid_buys
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
    except Exception as e:
        pass
    return None

def main():
    global GLOBAL_TARGET_DATE
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="YYYY-MM-DD", default=None)
    parser.add_argument("--reset", action="store_true", help="Reset params to default")
    args = parser.parse_args()
    
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
    print(f"======== 隔夜持股引擎启动 [{target_date}] ========")
    bs.login()
    state = load_state()
    
    if args.reset:
        print("📌 [系统提示] 已重置参数为常态/进攻默认值。")
        state["params"] = {
            "min_turnover": 200000000,
            "max_dist_ma10": 0.08,
            "max_amplitude": 0.13,
            "min_drop_5d": -0.15
        }
    
    # 1. 验证昨日胜率
    verify_yesterday(state, target_date)
    
    # 2. 根据胜率优化参数
    optimize_params(state, target_date)
    
    # 3. 扫描今日
    scan_today(state, target_date)
    
    save_state(state)
    bs.logout()
    print("==================================================")

if __name__ == "__main__":
    main()
