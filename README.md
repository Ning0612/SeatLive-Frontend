# SeatLive Frontend

安南屋-元智店 座位即時情況系統 - Streamlit 前端應用程式

## 🌐 線上 Demo

**正式部署**: [https://seatlive.streamlit.app](https://seatlive.streamlit.app)

## 📱 功能特色

### 1. 即時座位狀態
- 顯示餐廳座位配置圖（窗邊座位 + 四人桌）
- 即時更新座位佔用情況（每 5 秒自動刷新）
- 視覺化座位狀態（綠色=空位，紅色=已佔用）
- 顯示總座位數、已佔用、空位、佔用率

### 2. 熱門時段分析
- 周一到週五人流統計（每 10 秒自動刷新）
- 左右箭頭切換不同星期
- 膠囊圖顯示 9:00-21:00 的人流變化
- 根據當前星期自動顯示對應資料

### 3. 餐廳菜單
- 展開式菜單圖片瀏覽
- 線上菜單 PDF 連結

## 🚀 本地開發

### 安裝相依套件

```bash
pip install -r requirements.txt
```

### 設定環境變數

建立 `.streamlit/secrets.toml` 檔案：

```toml
# Firebase 憑證設定
FIREBASE_DATABASE_URL = "your_database_url"

[firebase]
type = "service_account"
project_id = "your_project_id"
private_key_id = "your_private_key_id"
private_key = "your_private_key"
client_email = "your_client_email"
client_id = "your_client_id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "your_cert_url"
```

### 啟動應用程式

```bash
streamlit run streamlit_app.py
```

應用程式將在 `http://localhost:8501` 啟動。

## 📊 資料來源

前端從 Firebase Realtime Database 讀取資料：

- `/seat_status`: 即時座位狀態
- `/occupancy_statistics/week_{n}`: 每週人流統計資料
  - `detail_data`: 詳細時段資料（15 分鐘區間）
  - `aggregated_data`: 聚合資料（按星期幾平均）

## 🎨 技術架構

- **框架**: Streamlit
- **圖表**: Plotly
- **資料處理**: Pandas
- **資料庫**: Firebase Realtime Database
- **部署**: Streamlit Cloud

## 📝 更新日誌

### 2025-12-26
- ✅ 將「現在時間」改為「上次資料更新時間」
- ✅ 將「近日人流統計」改為「熱門時段」
- ✅ 實作左右切換功能（周一到週五）
- ✅ 根據當前星期自動選擇預設顯示
- ✅ 修正統計資料計算邏輯（正確處理跨區間佔用）

### 2025-12-08
- 🎉 首次部署上線
- 實作即時座位狀態顯示
- 實作近日人流統計圖表
- 整合 Firebase Realtime Database

## 📄 授權

© 2025 安南屋-元智店 座位即時情況系統
