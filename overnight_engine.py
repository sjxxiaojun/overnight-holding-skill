#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
overnight_engine.py
隔夜持股 (Overnight Holding) 核心自适应引擎
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
            "min_turnover": 300000000,
            "max_dist_ma10": 0.12,
            "max_amplitude": 0.15,
            "min_drop_5d": -0.15
        },
        "history": {}
    }

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def get_trading_days():
    # Helper to determine roughly what the previous trading day is (for backtest logic)
    pass

def fetch_ohlc(symkey, limit=30):
    url = f"{BASE_URL}/app/api/v2/stocks/{symkey}/ohlcs?span=DAY1&limit={limit}"
    return safe_api_call(url)

def optimize_params(state, current_date):
    """根据最近两天的胜率自动调整参数"""
    history = state.get("history", {})
    dates = sorted(list(history.keys()))
    
    if len(dates) < 1:
        return
        
    last_date = dates[-1]
    if "win_rate" not in history[last_date]:
        return
        
    last_win_rate = history[last_date]["win_rate"]
    
    params = state["params"]
    print(f"\n[自适应优化] 前一日({last_date}) 胜率: {last_win_rate*100:.1f}%")
    
    if last_win_rate < 0.5:
        print("  -> 胜率偏低，系统自动【收紧】选股阈值 (防守模式)")
        params["min_turnover"] = min(800000000, int(params["min_turnover"] * 1.2))
        params["max_dist_ma10"] = max(0.01, params["max_dist_ma10"] * 0.8)
        params["max_amplitude"] = max(0.06, params["max_amplitude"] * 0.9)
        params["min_drop_5d"] = max(-0.08, params["min_drop_5d"] * 0.8)
    elif last_win_rate >= 0.7:
        print("  -> 胜率较高，系统自动【放宽】选股阈值 (进攻模式)")
        params["min_turnover"] = max(200000000, int(params["min_turnover"] * 0.9))
        params["max_dist_ma10"] = min(0.08, params["max_dist_ma10"] * 1.1)
        params["max_amplitude"] = min(0.15, params["max_amplitude"] * 1.1)
        params["min_drop_5d"] = min(-0.15, params["min_drop_5d"] * 1.1)
    else:
        print("  -> 胜率稳健，参数保持不变")
        
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
        
    # 避免重复验证
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
            if passed: # 只要次日有至少 2% 的冲高溢价即视为胜率有效 (吃肉)
                wins += 1
                
    if total > 0:
        win_rate = wins / total
        history[last_date]["win_rate"] = win_rate
        history[last_date]["verified_on"] = target_date_str
        print(f"验证完毕！共跟踪 {total} 只标的，其中 {wins} 只给出 >2% 的次日溢价空间。胜率: {win_rate*100:.1f}%\n")
    else:
        print(f"未找到 {target_date_str} 的行情数据进行验证，可能是节假日。\n")
        
def generate_stock_plan(name, is_chuangye):
    if "工业富联" in name:
        return "次日冲高优先兑现；弱开09:45不收复买入价退出"
    elif "澜起" in name:
        return "只做10日线附近修复，不追；弱开不收复退出"
    elif "兆易" in name:
        return "半导体强势但涨幅已大，必须区间内低吸"
    elif "中际" in name:
        return "光模块核心票回踩修复，高波动只试仓"
    elif "阳光" in name:
        return "储能/新能源方向放量修复，次日不强就按规则退出"
    
    if is_chuangye:
        return "高波动标的，注意10日线附近低吸试仓，次日弱开按规则退出"
    return "主板标的，次日冲高优先兑现；弱开跌破买入价分批退出"

def scan_today(state, target_date_str):
    print(f"📌 [2/3] 开始基于自适应参数扫描 {target_date_str} 尾盘标的...")
    params = state["params"]
    
    # 为了支持历史回测，我们拉取当前活跃度最高的前150只标的作为基础池
    url_params = {
        "order_by": "turnover desc",
        "page_no": 1,
        "page_size": 150
    }
    quotes_url = f"{BASE_URL}/app/api/v2/stocks?{urllib.parse.urlencode(url_params)}"
    data = safe_api_call(quotes_url)
    if not data or "stocks" not in data:
        print("无法获取股票列表")
        return
        
    candidates = [s for s in data["stocks"] if "ST" not in s["name"].upper() and "退" not in s["name"]]
    
    scored_stocks = []
    filtered_stocks = []
    
    print("📌 [3/3] 执行均线偏离与振幅严格过滤...")
    def fetch_single(s):
        symkey = s["symkey"]
        name = s["name"]
        ohlc_data = fetch_ohlc(symkey, limit=60)
        if not ohlc_data or "ohlcs" not in ohlc_data or len(ohlc_data["ohlcs"]) < 10:
            return None
        return (s, ohlc_data)

    stock_data_list = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        results = executor.map(fetch_single, candidates)
        for r in results:
            if r is not None:
                stock_data_list.append(r)

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
        
        # 手动计算目标日期的涨跌幅和振幅
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
        
        if change_rate < -0.02 or change_rate > 0.035:
            is_filtered = True
            if change_rate < -0.02:
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
            
        # 形态打分
        score = 0
        if ma10_val > ma20_val: score += 30
        if c_t > o_t: score += 20
        body = abs(c_t - o_t) / (h_t - l_t + 1e-6)
        if body < 0.4: score += 20
        
        # 科技主线龙头核心加分
        mainline_keywords = ["富联", "旭创", "澜起", "兆易", "阳光电源", "芯片", "半导体", "光通信", "光模块", "服务器", "储能"]
        is_mainline = any(kw in name for kw in mainline_keywords)
        if is_mainline:
            score += 30
        
        if score > 30:
            scored_stocks.append({
                "symkey": symkey,
                "name": name,
                "score": score,
                "buy_price": c_t
            })
            
    scored_stocks.sort(key=lambda x: x["score"], reverse=True)
    top_picks = scored_stocks[:5]
    
    # 填充交易计划信息
    for p in top_picks:
        buy_p = p["buy_price"]
        p["trigger_low"] = round(buy_p * 0.99, 2)
        p["trigger_high"] = round(buy_p * 1.005, 2)
        p["stop_loss"] = round(buy_p * 0.972, 2)
        p["take_profit"] = round(buy_p * 1.027, 2)
        p["position"] = "8%"
        is_cyb = p["symkey"].startswith("300") or p["symkey"].startswith("688")
        p["plan"] = generate_stock_plan(p["name"], is_cyb)
        
    print(f"\n【扫描结果】{target_date_str} 建议尾盘潜伏名单：")
    for i, p in enumerate(top_picks):
        print(f"  {i+1}. {p['name']} ({p['symkey']}) - 信号价: {p['buy_price']}")
        print(f"     [计划表] 触发区间: {p['trigger_low']}-{p['trigger_high']} | 止损: {p['stop_loss']} | 止盈: {p['take_profit']} | 仓位: {p['position']}")
        print(f"     [操盘计划] {p['plan']}")
        
    print(f"\n【容易误买但今日不建议抄底】：")
    # 挑选容易误买但今日不建议抄底的三只典型标的
    avoid_list = []
    
    # 热门主线避雷关键词列表
    avoid_keywords = ["卫星", "航天", "军工", "光", "芯", "科技", "通信", "半导体", "智能", "阳光", "富联", "旭创", "澜起", "兆易", "电子", "芯原", "光迅"]
    
    # 1. 寻找“高位急跌接飞刀”代表（优先在匹配热门关键词的股中寻找跌停或跌幅大、5日跌幅惨烈的）
    fei_dao = None
    for fs in filtered_stocks:
        if fs["change_rate"] <= -0.06 and fs["change_rate"] < 0.19:
            is_main = any(kw in fs["name"] for kw in avoid_keywords)
            if is_main:
                if fei_dao is None or fs["drop_5d"] < fei_dao["drop_5d"]:
                    fei_dao = fs
    if fei_dao is None:
        for fs in filtered_stocks:
            if fs["change_rate"] <= -0.06 and fs["change_rate"] < 0.19:
                if fei_dao is None or fs["drop_5d"] < fei_dao["drop_5d"]:
                    fei_dao = fs
    if fei_dao:
        avoid_list.append(fei_dao)
        
    # 2. 寻找“涨幅大但非低吸点，易分歧”代表（优先寻找涨幅大、未涨停但属于热门题材的股票）
    fen_qi = None
    for fs in filtered_stocks:
        if fs not in avoid_list and fs["change_rate"] >= 0.08 and fs["change_rate"] < 0.19:
            is_main = any(kw in fs["name"] for kw in avoid_keywords)
            is_limit_up = (abs(fs["change_rate"] - 0.1) < 0.01) or (abs(fs["change_rate"] - 0.2) < 0.01)
            if is_main and not is_limit_up:
                if fen_qi is None or fs["change_rate"] > fen_qi["change_rate"]:
                    fen_qi = fs
    if fen_qi is None:
        for fs in filtered_stocks:
            if fs not in avoid_list and fs["change_rate"] >= 0.08 and fs["change_rate"] < 0.19:
                is_limit_up = (abs(fs["change_rate"] - 0.1) < 0.01) or (abs(fs["change_rate"] - 0.2) < 0.01)
                if not is_limit_up:
                    if fen_qi is None or fs["change_rate"] > fen_qi["change_rate"]:
                        fen_qi = fs
    if fen_qi:
        avoid_list.append(fen_qi)
        
    # 3. 寻找“位置偏高，偏离均线过远”代表（优先寻找偏离MA10过远的热门主线股）
    pian_gao = None
    for fs in filtered_stocks:
        if fs not in avoid_list and fs["change_rate"] < 0.19:
            is_main = any(kw in fs["name"] for kw in avoid_keywords)
            if is_main and fs["dist_ma10"] > 0.10:
                if pian_gao is None or fs["dist_ma10"] > pian_gao["dist_ma10"]:
                    pian_gao = fs
    if pian_gao is None:
        for fs in filtered_stocks:
            if fs not in avoid_list and fs["change_rate"] < 0.19:
                if pian_gao is None or fs["dist_ma10"] > pian_gao["dist_ma10"]:
                    pian_gao = fs
    if pian_gao:
        avoid_list.append(pian_gao)
        
    # 兜底：如果不够3个，按原顺序填充且排除 20cm 涨停股
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
    # 获取工业富联的最新 K 线日期，以此判断最新交易日
    url = f"{BASE_URL}/app/api/v2/stocks/601138.XSHG/ohlcs?span=DAY1&limit=2"
    res = safe_api_call(url)
    if res and "ohlcs" in res and res["ohlcs"]:
        last_candle = res["ohlcs"][-1]
        ts = last_candle.get("otm", 0) / 1000.0
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    return None

def main():
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
            
    print(f"======== 隔夜持股引擎启动 [{target_date}] ========")
    state = load_state()
    
    if args.reset:
        print("📌 [系统提示] 检测到 --reset，已强制重置自适应参数为默认值。")
        state["params"] = {
            "min_turnover": 300000000,
            "max_dist_ma10": 0.12,
            "max_amplitude": 0.15,
            "min_drop_5d": -0.15
        }
    
    # 1. 验证昨日胜率
    verify_yesterday(state, target_date)
    
    # 2. 根据胜率优化参数
    optimize_params(state, target_date)
    
    # 3. 扫描今日
    scan_today(state, target_date)
    
    save_state(state)
    print("==================================================")

if __name__ == "__main__":
    main()
