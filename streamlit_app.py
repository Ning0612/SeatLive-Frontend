"""
SeatLive Streamlit 前端應用程式

顯示餐廳座位即時狀態和本週人流統計
資料來源：Firebase Realtime Database
"""
import os
import sys
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timezone, timedelta
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
import glob
import re
import streamlit.components.v1 as components

# 載入環境變數
load_dotenv()

# 頁面設定
st.set_page_config(
    page_title="安南屋-元智店 - 座位即時情況",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS 樣式
st.markdown("""
<style>
    /* 移除 Streamlit 預設邊距以適配手機 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 100%;
    }

    /* 背景透明以適配深色模式 */
    .stApp {
        background: transparent;
    }

    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1.5rem;
        margin-top: 1rem;
        line-height: 1.2;
    }

    /* 手機端適配標題 */
    @media (max-width: 768px) {
        .main-header {
            font-size: 1.8rem;
            margin-bottom: 1rem;
        }
    }

    .metric-card {
        background-color: rgba(240, 242, 246, 0.5);
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }

    /* 強制 metric 數值和標籤置中 */
    [data-testid="stMetricValue"] {
        text-align: center !important;
        justify-content: center !important;
        display: flex !important;
        width: 100% !important;
    }

    [data-testid="stMetricLabel"] {
        text-align: center !important;
        justify-content: center !important;
        display: flex !important;
        width: 100% !important;
    }

    [data-testid="metric-container"] {
        text-align: center !important;
    }

    /* 底部版權資訊樣式 */
    .footer {
        text-align: center;
        color: #666;
        padding: 2rem 0 2rem 0;
        font-size: 0.875rem;
        border-top: 1px solid rgba(128, 128, 128, 0.2);
        margin-top: 3rem;
        margin-bottom: 0;
        width: 100%;
        clear: both;
    }

    /* 免責聲明樣式 */
    .disclaimer {
        text-align: center;
        color: #999;
        font-size: 0.75rem;
        padding: 0.5rem;
        margin-top: 1rem;
        font-style: italic;
    }

    /* 手機端適配 */
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.5rem;
            padding-right: 0.5rem;
            padding-bottom: 2rem;
        }

        .footer {
            font-size: 0.75rem;
            padding: 1.5rem 0 1.5rem 0;
        }
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def initialize_firebase():
    """初始化 Firebase 連接（支援本地開發和 Streamlit Cloud）"""
    try:
        # 檢查是否已經初始化
        if not firebase_admin._apps:
            # 優先使用 Streamlit secrets（用於 Streamlit Cloud 部署）
            if 'firebase' in st.secrets:
                # Streamlit Cloud 模式
                cred = credentials.Certificate(dict(st.secrets['firebase']))
                database_url = st.secrets['FIREBASE_DATABASE_URL']
            else:
                # 本地開發模式：使用環境變數
                credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH')
                database_url = os.getenv('FIREBASE_DATABASE_URL')

                if not credentials_path or not database_url:
                    st.error("❌ 未設定 Firebase 憑證，請檢查 .env 檔案或 Streamlit Secrets")
                    return False

                # 取得憑證檔案完整路徑（專案根目錄）
                if not os.path.isabs(credentials_path):
                    # frontend/streamlit_app.py -> frontend/ -> project_root/
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    credentials_path = os.path.join(base_dir, credentials_path)

                if not os.path.exists(credentials_path):
                    st.error(f"❌ 找不到 Firebase 憑證檔案: {credentials_path}")
                    return False

                cred = credentials.Certificate(credentials_path)

            # 初始化 Firebase
            firebase_admin.initialize_app(cred, {
                'databaseURL': database_url
            })

        return True
    except Exception as e:
        st.error(f"❌ Firebase 初始化失敗: {e}")
        import traceback
        st.error(f"詳細錯誤：\n```\n{traceback.format_exc()}\n```")
        return False


def get_seat_status():
    """從 Firebase 讀取即時座位狀態"""
    try:
        ref = db.reference('/seat_status')
        data = ref.get()

        if not data:
            return None

        # 轉換為 DataFrame
        seats_list = []
        for seat_id, info in data.items():
            seats_list.append({
                'seat_id': seat_id,
                'status': info.get('status', 'unknown'),
                'status_zh': info.get('status_zh', '未知'),
                'last_update': info.get('last_update', '')
            })

        df = pd.DataFrame(seats_list)
        df = df.sort_values('seat_id')
        return df

    except Exception as e:
        st.error(f"❌ 讀取座位狀態失敗: {e}")
        return None


def get_weekday_aggregated_occupancy():
    """
    從 Firebase 讀取周一到週五的聚合統計資料

    動態查找每個星期最新有資料的週次（支援跨年查詢）
    - 往前查詢最多 12 週（約 3 個月）
    - 對每個星期（週一到週五）分別找出最新有資料的週次

    Returns:
        dict: {weekday: DataFrame} 格式，weekday 為 0-4（週一到週五）
    """
    try:
        # 取得當前週次
        current_week = datetime.now().isocalendar()[1]

        # 計算要查詢的週次範圍（往前查 12 週，約 3 個月，支援跨年）
        weeks_to_fetch = []
        for i in range(12):
            week_num = current_week - i
            if week_num > 0:
                weeks_to_fetch.append(week_num)
            else:
                # 跨年情況：計算前一年的週次
                # ISO 週次系統中，一年有 52 或 53 週
                # week_num = 0 → 前一年第 53 週
                # week_num = -1 → 前一年第 52 週
                # week_num = -2 → 前一年第 51 週，以此類推
                previous_year_week = 53 + week_num
                if previous_year_week > 0:  # 確保週次有效
                    weeks_to_fetch.append(previous_year_week)

        # 收集所有週次的資料（按星期分組）
        weekday_data_by_week = {weekday: [] for weekday in range(5)}  # 0-4 代表週一到週五

        # 從可能的週次中取得詳細資料
        for week_num in weeks_to_fetch:
            ref = db.reference(f'/occupancy_statistics/week_{week_num}')
            data = ref.get()

            if data and 'detail_data' in data:
                detail_df = pd.DataFrame(data['detail_data'])
                if not detail_df.empty:
                    # 確保有必要的欄位
                    if 'datetime' in detail_df.columns:
                        detail_df['datetime'] = pd.to_datetime(detail_df['datetime'])

                    # 按星期分組儲存資料
                    for weekday in range(5):  # 只處理週一到週五
                        weekday_df = detail_df[detail_df['weekday'] == weekday].copy()
                        if not weekday_df.empty:
                            # 記錄這個週次和對應的資料
                            weekday_data_by_week[weekday].append({
                                'week_num': week_num,
                                'data': weekday_df
                            })

        # 對每個星期，只保留最新有資料的週次
        all_latest_data = []
        for weekday in range(5):
            if weekday_data_by_week[weekday]:
                # 取得該星期最新的資料（第一個就是最新的，因為 weeks_to_fetch 是從新到舊排序）
                latest_data = weekday_data_by_week[weekday][0]['data']
                all_latest_data.append(latest_data)

        if not all_latest_data:
            return None

        # 合併所有星期的最新資料
        combined_df = pd.concat(all_latest_data, ignore_index=True)

        # 按星期幾和時段聚合（取平均值）
        aggregated = combined_df.groupby(['weekday', 'weekday_zh', 'time_interval']).agg({
            'occupancy_count': 'mean'
        }).reset_index()

        aggregated['occupancy_count'] = aggregated['occupancy_count'].round(1)

        # 將資料按星期分組
        weekday_data = {}
        for weekday in range(5):  # 0=週一, 4=週五
            weekday_df = aggregated[aggregated['weekday'] == weekday].copy()
            if not weekday_df.empty:
                # 提取時間資訊
                weekday_df['hour'] = weekday_df['time_interval'].str.split('-').str[0].str.split(':').str[0].astype(int)
                weekday_df['minute'] = weekday_df['time_interval'].str.split('-').str[0].str.split(':').str[1].astype(int)
                weekday_data[weekday] = weekday_df

        return weekday_data if weekday_data else None

    except Exception as e:
        st.error(f"❌ 讀取熱門時段統計失敗: {e}")
        return None


@st.fragment(run_every="5s")
def display_live_seat_status():
    """即時座位狀態區塊（每 5 秒自動更新）"""
    # 讀取座位狀態
    df = get_seat_status()

    if df is None or df.empty:
        st.warning("⚠️ 目前沒有座位狀態資料")
        return

    # 統計資訊
    total_seats = len(df)
    occupied_seats = len(df[df['status'] == 'occupied'])
    available_seats = total_seats - occupied_seats
    occupancy_rate = (occupied_seats / total_seats * 100) if total_seats > 0 else 0

    # 顯示上次資料更新時間（從座位狀態資料中取得最新的 last_update，暫時註解移除顯示）
    # try:
    #     # 取得所有座位的 last_update 時間，找出最新的一筆
    #     last_updates = df['last_update'].dropna()
    #     if not last_updates.empty:
    #         # 找出最新的更新時間
    #         latest_update = max(pd.to_datetime(last_updates))
    #         update_time_str = latest_update.strftime('%Y-%m-%d %H:%M:%S')
    #         st.caption(f"🕒 上次資料更新時間：{update_time_str}")
    #     else:
    #         st.caption(f"🕒 上次資料更新時間：無資料")
    # except Exception as e:
    #     # 如果解析失敗，顯示當前時間作為備用
    #     utc8_timezone = timezone(timedelta(hours=8))
    #     current_time = datetime.now(utc8_timezone).strftime('%Y-%m-%d %H:%M:%S')
    #     st.caption(f"🕒 現在時間：{current_time}")

    # 顯示統計卡片
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("總座位數", f"{total_seats} 個")

    with col2:
        st.metric("已佔用", f"{occupied_seats} 個")

    with col3:
        st.metric("空位", f"{available_seats} 個")

    with col4:
        # 根據佔用率設定顏色
        if occupancy_rate <= 30:
            color = "#51cf66"  # 綠色（低佔用）
        elif occupancy_rate <= 70:
            color = "#ffd43b"  # 黃色（中等佔用）
        else:
            color = "#ff6b6b"  # 紅色（高佔用）

        st.markdown(
            f'<div style="text-align: center;">'
            f'<p style="font-size: 0.875rem; color: #666; margin-bottom: 0.25rem;">佔用率</p>'
            f'<p style="font-size: 2rem; font-weight: bold; color: {color}; margin: 0;">{occupancy_rate:.1f}%</p>'
            f'</div>',
            unsafe_allow_html=True
        )

    # 座位配置示意圖
    st.markdown("#### 座位配置圖")

    # 定義座位位置（根據圖片的相對位置）
    seat_positions = {
        # 窗邊座位（W1-W6）- 上方橫排
        'W1': (1, 5), 'W2': (2, 5), 'W3': (3, 5),
        'W4': (4, 5), 'W5': (5, 5), 'W6': (6, 5),

        # 窗邊座位（W7-W12）- 右側縱排
        'W7': (7, 4), 'W8': (7, 3), 'W9': (7, 2),
        'W10': (7, 1), 'W11': (7, 0), 'W12': (7, -1),

        # 四人桌（T1-T4）- 中央 2x2 排列
        'T1': (1.5, 2.5), 'T2': (4.5, 2.5),
        'T3': (1.5, 0), 'T4': (4.5, 0)
    }

    # 建立座位狀態列表
    seat_data = []
    for seat_id, (x, y) in seat_positions.items():
        status = df[df['seat_id'] == seat_id]['status'].values[0] if seat_id in df['seat_id'].values else 'available'
        is_occupied = (status == 'occupied')

        seat_data.append({
            'seat_id': seat_id,
            'x': x,
            'y': y,
            'status': '佔用' if is_occupied else '空位',
            'color': '#ff6b6b' if is_occupied else '#51cf66',
            'size': 80 if seat_id.startswith('T') else 40  # 四人桌較大
        })

    seat_df = pd.DataFrame(seat_data)

    # 使用 Plotly 繪製座位配置圖
    fig = go.Figure()

    # 添加座位標記（改為矩形）
    for _, row in seat_df.iterrows():
        # 計算矩形大小
        rect_size = 0.4 if row['seat_id'].startswith('T') else 0.25
        font_size = 12 if row['seat_id'].startswith('T') else 10

        # 添加矩形背景
        fig.add_shape(
            type="rect",
            x0=row['x'] - rect_size, y0=row['y'] - rect_size,
            x1=row['x'] + rect_size, y1=row['y'] + rect_size,
            fillcolor=row['color'],
            line=dict(width=2, color='#333'),
        )

        # 只添加座位 ID 文字（白色），狀態用顏色表示
        fig.add_annotation(
            x=row['x'],
            y=row['y'],
            text=row['seat_id'],
            font=dict(size=font_size, color='white', family='Arial Black'),
            showarrow=False,
            xanchor='center',
            yanchor='middle'
        )

        # 添加隱形的 hover 點
        fig.add_trace(go.Scatter(
            x=[row['x']],
            y=[row['y']],
            mode='markers',
            marker=dict(size=1, opacity=0),
            name=row['seat_id'],
            showlegend=False,
            hovertemplate=f"<b>{row['seat_id']}</b><br>狀態: {row['status']}<extra></extra>"
        ))

    # 添加門的位置標記（右下角）
    fig.add_annotation(
        x=7.5, y=-2,
        text="門",
        showarrow=False,
        font=dict(size=14, color='#666'),
        bordercolor="#666",
        borderwidth=2,
        borderpad=4,
        bgcolor="#f0f0f0"
    )

    # 添加窗的位置標記（上方）
    fig.add_annotation(
        x=3.5, y=5.8,
        text="窗",
        showarrow=False,
        font=dict(size=14, color='#666'),
        bordercolor="#666",
        borderwidth=2,
        borderpad=4,
        bgcolor="#f0f0f0"
    )

    # 設定圖表佈局（鎖定不可拖拉或縮放）
    fig.update_layout(
        height=500,
        xaxis=dict(
            range=[-0.5, 8.5],
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            fixedrange=True  # 鎖定 X 軸
        ),
        yaxis=dict(
            range=[-2.5, 6.5],
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            fixedrange=True  # 鎖定 Y 軸
        ),
        plot_bgcolor='rgba(248, 249, 250, 0.5)',
        margin=dict(l=20, r=20, t=20, b=20),
        hovermode='closest',
        dragmode=False  # 必須禁用以修復手機滾動問題
    )

    st.plotly_chart(fig, width='stretch', config={
        'displayModeBar': False,
        'scrollZoom': False  # 禁用滾輪縮放，確保觸控滾動正常
    })

    # 圖例說明
    col_legend1, col_legend2 = st.columns(2)
    with col_legend1:
        st.markdown('<div style="background-color: #ff6b6b; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">🔴 已佔用</div>', unsafe_allow_html=True)
    with col_legend2:
        st.markdown('<div style="background-color: #51cf66; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">🟢 空位</div>', unsafe_allow_html=True)

    # 免責聲明
    st.markdown('<div class="disclaimer">⚠️ 因延遲及辨識準確性，即時狀態僅供參考，請以實際現場狀況為主</div>', unsafe_allow_html=True)


@st.fragment(run_every="10s")
def display_live_statistics():
    """熱門時段區塊（使用 st.tabs 避免 FOUC，客戶端切換無延遲）"""
    # 讀取周一到週五的聚合資料
    weekday_data = get_weekday_aggregated_occupancy()

    if weekday_data is None or len(weekday_data) == 0:
        st.info("ℹ️ 暫無熱門時段資料")
        return

    weekday_names = ['週一', '週二', '週三', '週四', '週五']

    # 決定預設顯示哪一天
    current_weekday = datetime.now().weekday()
    if current_weekday >= 5:
        default_weekday = 0
    else:
        default_weekday = current_weekday

    # CSS：隱藏原生的 tabs 標籤列 + 優化按鈕佈局
    st.markdown("""
    <style>
    /* 隱藏原生 Tabs 的標籤列 */
    .stTabs [data-baseweb="tab-list"] {
        display: none !important;
    }

    /* 針對手機端優化星期選擇器 */
    @media (max-width: 576px) {
        #weekday-selector {
            gap: 0.5rem !important;
        }
        #weekday-selector button {
            padding: 0.4rem 0.8rem !important;
            font-size: 0.9rem !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    # UI 佈局（按鈕 + 星期名稱在同一個水平容器中）
    st.markdown(f"""
    <div id="weekday-selector" style="
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 1rem;
        margin: 1rem 0;
        flex-wrap: nowrap;
        width: 100%;">
        <button id="btn-prev" style="
            background: #f0f2f6;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 0.5rem 1rem;
            cursor: pointer;
            font-size: 1rem;
            flex-shrink: 0;
            line-height: 1;">
            ◀
        </button>
        <div id="weekday-title" style="
            font-size: 1.2rem;
            font-weight: bold;
            min-width: 60px;
            text-align: center;
            white-space: nowrap;">
            {weekday_names[default_weekday]}
        </div>
        <button id="btn-next" style="
            background: #f0f2f6;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 0.5rem 1rem;
            cursor: pointer;
            font-size: 1rem;
            flex-shrink: 0;
            line-height: 1;">
            ▶
        </button>
    </div>
    """, unsafe_allow_html=True)

    # 找出所有資料中的最大佔用數（統一標準化高度）
    all_max_occupancy = 1
    for weekday in range(5):
        if weekday in weekday_data:
            interval_data = weekday_data[weekday]
            interval_data = interval_data[(interval_data['hour'] >= 9) & (interval_data['hour'] < 21)].copy()
            if not interval_data.empty:
                max_occ = interval_data['occupancy_count'].max()
                if max_occ > all_max_occupancy:
                    all_max_occupancy = max_occ

    # 使用 st.tabs 創建五個標籤頁（原生支援，無 FOUC）
    tabs = st.tabs(weekday_names)

    # 在每個 tab 中渲染對應的圖表
    for weekday, tab in enumerate(tabs):
        with tab:
            if weekday not in weekday_data:
                st.info("ℹ️ 暫無資料")
                continue

            interval_data = weekday_data[weekday]
            interval_data = interval_data[(interval_data['hour'] >= 9) & (interval_data['hour'] < 21)].copy()

            if interval_data.empty:
                st.info("ℹ️ 暫無資料")
                continue

            # 計算時間軸位置
            interval_data['time_position'] = (interval_data['hour'] - 9) + (interval_data['minute'] / 60)

            # 繪製膠囊圖
            fig = go.Figure()

            for _, row in interval_data.iterrows():
                time_pos = row['time_position']
                occupancy = row['occupancy_count']
                height = (occupancy / all_max_occupancy) * 0.8 if all_max_occupancy > 0 else 0

                if occupancy >= all_max_occupancy * 0.8:
                    color = '#d946a6'
                elif occupancy >= all_max_occupancy * 0.5:
                    color = '#94a3b8'
                else:
                    color = '#94a3b8'

                fig.add_shape(
                    type="rect",
                    x0=time_pos - 0.1, x1=time_pos + 0.1,
                    y0=0, y1=height,
                    fillcolor=color,
                    line=dict(width=0),
                    opacity=0.8
                )

                if row['minute'] == 0:
                    fig.add_annotation(
                        x=time_pos,
                        y=height + 0.05,
                        text=f"{occupancy:.0f}",
                        showarrow=False,
                        font=dict(size=9, color='#666'),
                        yanchor='bottom'
                    )

            fig.update_layout(
                height=150,
                xaxis=dict(
                    tickmode='array',
                    tickvals=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                    ticktext=['9時', '10時', '11時', '12時', '13時', '14時', '15時', '16時', '17時', '18時', '19時', '20時', '21時'],
                    range=[-0.3, 12],
                    showgrid=False,
                    fixedrange=True
                ),
                yaxis=dict(
                    showticklabels=False,
                    showgrid=False,
                    range=[0, 1],
                    fixedrange=True
                ),
                margin=dict(l=10, r=10, t=10, b=30),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                dragmode=False,
                hovermode=False
            )

            st.plotly_chart(fig, width='stretch', config={
                'displayModeBar': False,
                'scrollZoom': False
            }, key=f"weekday_chart_{weekday}")

    # 滑動提示
    st.markdown("""
    <div style="text-align: center; color: #999; font-size: 0.75rem; margin-top: 0.5rem;">
        💡 提示：點擊左右按鈕可切換星期
    </div>
    """, unsafe_allow_html=True)

    # JavaScript：控制 st.tabs 切換與滑動手勢
    components.html(f"""
    <script>
    (function() {{
        const weekdayNames = ['週一', '週二', '週三', '週四', '週五'];
        let currentWeekday = {default_weekday};
        let tabButtons = [];
        let isInitialized = false;
        let touchStartX = 0;
        let touchEndX = 0;

        // 切換到指定的星期（透過點擊 st.tabs 的 tab button）
        function switchWeekday(newWeekday) {{
            if (newWeekday < 0 || newWeekday > 4) return;
            if (tabButtons.length !== 5) return;

            // 點擊對應的 tab button
            tabButtons[newWeekday].click();
            currentWeekday = newWeekday;

            // 更新自訂的星期標題
            const title = window.parent.document.getElementById('weekday-title');
            if (title) title.textContent = weekdayNames[newWeekday];
        }}

        // 綁定按鈕點擊與滑動事件
        function bindEvents() {{
            // 綁定左右箭頭按鈕
            const btnPrev = window.parent.document.getElementById('btn-prev');
            const btnNext = window.parent.document.getElementById('btn-next');

            if (btnPrev) {{
                btnPrev.addEventListener('click', function() {{
                    switchWeekday((currentWeekday - 1 + 5) % 5);
                }}, {{ passive: true }});
            }}

            if (btnNext) {{
                btnNext.addEventListener('click', function() {{
                    switchWeekday((currentWeekday + 1) % 5);
                }}, {{ passive: true }});
            }}

            // 在圖表區域綁定滑動手勢
            const tabContent = window.parent.document.querySelector('[data-testid="stTabs"]');
            if (tabContent) {{
                tabContent.addEventListener('touchstart', function(e) {{
                    touchStartX = e.changedTouches[0].clientX;
                }}, {{ passive: true }});

                tabContent.addEventListener('touchend', function(e) {{
                    // 檢查是否在 Plotly 圖表上滑動（避免與圖表交互衝突）
                    if (e.target.closest('.js-plotly-plot') || e.target.closest('[data-testid="stPlotlyChart"]')) {{
                        return; // 在圖表上的滑動不觸發切換
                    }}

                    touchEndX = e.changedTouches[0].clientX;
                    const swipeDiff = touchStartX - touchEndX;

                    // 滑動距離超過 80px 才觸發切換
                    if (Math.abs(swipeDiff) > 80) {{
                        if (swipeDiff > 0) {{
                            // 向左滑動：下一天
                            switchWeekday((currentWeekday + 1) % 5);
                        }} else {{
                            // 向右滑動：上一天
                            switchWeekday((currentWeekday - 1 + 5) % 5);
                        }}
                    }}
                }}, {{ passive: true }});
            }}
        }}

        // 初始化
        function init() {{
            if (isInitialized) return;

            // 設定初始 tab
            switchWeekday(currentWeekday);

            // 綁定事件
            bindEvents();

            isInitialized = true;
        }}

        // 等待 st.tabs 的 tab buttons 載入完成
        function waitForTabs() {{
            const targetNode = window.parent.document.querySelector('[data-testid="stAppViewContainer"]');
            if (!targetNode) {{
                setTimeout(waitForTabs, 100);
                return;
            }}

            const observer = new MutationObserver((mutationsList, observer) => {{
                // 尋找 st.tabs 的 tab buttons（被我們用 CSS 隱藏的那些）
                const buttons = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
                if (buttons.length >= 5) {{
                    tabButtons = Array.from(buttons);
                    init();
                    observer.disconnect();
                }}
            }});

            observer.observe(targetNode, {{ childList: true, subtree: true }});

            // 5 秒後強制停止監聽
            setTimeout(() => {{
                observer.disconnect();
                if (!isInitialized) {{
                    // 備用方案：直接嘗試取得 tab buttons
                    const buttons = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
                    if (buttons.length >= 5) {{
                        tabButtons = Array.from(buttons);
                        init();
                    }}
                }}
            }}, 5000);
        }}

        // 啟動
        waitForTabs();
    }})();
    </script>
    """, height=0)


def display_main_page():
    """顯示主頁面（標題、即時狀態、統計、菜單）"""
    # 主標題
    st.markdown('<div class="main-header">🍽️ 安南屋-元智店 座位即時情況</div>', unsafe_allow_html=True)

    # ============================================================
    # 即時座位狀態區塊（每 5 秒自動更新）
    # ============================================================
    st.subheader("📊 即時座位狀態")
    display_live_seat_status()

    st.divider()

    # ============================================================
    # 熱門時段區塊（每 10 秒自動更新）
    # ============================================================
    st.subheader("📈 熱門時段")
    display_live_statistics()

    st.divider()

    # ============================================================
    # 餐廳菜單區塊（靜態內容）
    # ============================================================
    st.subheader("🍽️ 餐廳菜單")

    # 讀取菜單圖片檔案
    menu_dir = os.path.join(os.path.dirname(__file__), 'menu')
    menu_files = sorted(glob.glob(os.path.join(menu_dir, 'menu_*.jpg')))

    if menu_files:
        # 從檔名提取日期（例如：menu_2025_12_08-1.jpg -> 2025-12-08）
        first_file = os.path.basename(menu_files[0])
        date_match = re.search(r'menu_(\d{4})_(\d{2})_(\d{2})', first_file)

        if date_match:
            menu_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            st.caption(f"📅 菜單更新日期：{menu_date}")

        # 餐廳資訊
        st.markdown("""
        **🏪 餐廳名稱**：安南屋-元智店
        **📋 線上菜單**：[點此查看完整菜單 PDF](https://www.yzu.edu.tw/admin/st/files/%E5%AE%BF%E6%9C%8D%E7%B5%84/%E5%AD%B8%E9%A4%90/113-1%E5%AD%B8%E6%9C%9F/%E5%AE%89%E5%8D%97%E5%B1%8B-%E8%8F%9C%E5%96%AE.pdf)
        **⚠️ 免責聲明**：菜單內容僅供參考，實際供餐狀況請以餐廳現場為主
        """)

        # 使用 expander 顯示菜單圖片（避免佔用過多空間）
        with st.expander("📖 點此展開查看菜單圖片", expanded=False):
            for i, menu_file in enumerate(menu_files):
                st.image(menu_file, caption=f"菜單頁面 {i+1}", width="stretch")
    else:
        st.info("ℹ️ 目前尚無菜單圖片")
        st.markdown("""
        **🏪 餐廳名稱**：安南屋-元智店
        **📋 線上菜單**：[點此查看完整菜單 PDF](https://www.yzu.edu.tw/admin/st/files/%E5%AE%BF%E6%9C%8D%E7%B5%84/%E5%AD%B8%E9%A4%90/113-1%E5%AD%B8%E6%9C%9F/%E5%AE%89%E5%8D%97%E5%B1%8B-%E8%8F%9C%E5%96%AE.pdf)
        **⚠️ 免責聲明**：菜單內容僅供參考，實際供餐狀況請以餐廳現場為主
        """)

    # 不在這裡自動重新整理，改到 main() 函數最後


# ============================================================
# 主程式
# ============================================================

def main():
    # 初始化 Firebase
    if not initialize_firebase():
        st.stop()

    # 顯示主頁面（包含自動更新的 fragments）
    display_main_page()

    # 底部版權資訊
    st.markdown('<div class="footer">© 2025 安南屋-元智店 座位即時情況系統</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
