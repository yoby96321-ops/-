00403A 手機版行情頁
====================

架構
----
1. 家裡 Windows 電腦執行 publish_yuanta.py，使用元大 SPARK API 唯讀取得即時報價。
2. 每分鐘收集一筆當日價格，每 5 分鐘把行情、預測曲線與比較資料更新到 GitHub 的 mobile_dashboard/data.json。
3. GitHub Pages 提供手機網頁。手機頁面每 60 秒讀一次最新 JSON。

重要：GitHub Pages 這種公開網站任何人拿到網址都能看；目前頁面只發布 00403A 行情、預測和走勢，不發布你的元大帳密、持股或成本。不要把 API 密碼或 GitHub token 放進 repository。

第一次部署
----------
1. 建立一個新的 GitHub repository。若要使用 GitHub Pages 免費方案，將 repository 設為 Public；此時網站與行情資料也會公開。
2. 把本資料夾的內容放到 repository 根目錄下的 mobile_dashboard/。
3. 把專案根目錄的 .github/workflows/pages.yml 一併放到 repository 的 .github/workflows/pages.yml。
4. 在 repository 的 Settings → Pages → Build and deployment，將 Source 選成 GitHub Actions。
5. 等 GitHub Actions 完成後，在 Actions 的部署工作中查看 Pages 網址；手機用瀏覽器打開並加入主畫面即可。

本機發布器
----------
1. 保持以下相對資料夾結構：股票/（主程式與模型）、data/00403A_yuanta_5m.csv（歷史資料）、YuantaSparkAPI_win-x64_Python/（元大元件）。確認歷史檔至少有 20 個完整交易日。
2. 安裝 Python 3.11、pythonnet、pandas、numpy、yfinance（原本主程式已安裝的套件可沿用）。
3. 建立 fine-grained GitHub token，只授權該 repository 的 Contents: Read and write。Token 只在發布器執行時輸入，不要貼到聊天或程式檔。
4. 執行專案根目錄 mobile_dashboard/ 裡的 啟動手機資料發布器.bat，依提示填 repository（owner/name）、GitHub token、元大 API 帳號和密碼。
5. 黑色視窗需保持開啟、電腦需保持開機和連網；按 Ctrl+C 停止。

限制
----
- GitHub 是程式碼與靜態頁面託管，不會替你連元大 API；本機發布器必須持續執行。
- 每 5 分鐘一筆 GitHub 資料更新，網頁每 60 秒檢查一次。GitHub API、網路或電腦中斷時，頁面會保留最後成功資料。
- 預測使用相似歷史交易日估算，不能保證準確；請把預測與實際曲線的誤差一併參考。
- 成交量單位依元大 API 回傳，尚未自行換算為張或股。

