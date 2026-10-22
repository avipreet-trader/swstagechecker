# Weinstein Stage Checker (Yahoo Finance edition)

A free web app that marks any NSE or BSE stock with Stan Weinstein's Stages 1–4.
It shows weekly candles, the 30-week moving average, volume, Mansfield relative
strength vs Nifty 50, a Stage 2 checklist and a stage key. Data comes from
Yahoo Finance, so nobody needs a Zerodha or Kite login.

## Put it online (about 10 minutes, one time)

You need a free GitHub account and a free Streamlit Community Cloud account.

1. **Create a GitHub repository**
   - Go to github.com, sign in (or sign up), click **New repository**.
   - Name it `stage-checker`, choose **Public**, tick **Add a README file**, click **Create repository**.

2. **Upload the app files**
   - In the new repository click **Add file → Upload files**.
   - Unzip this folder on your computer and drag in everything inside it:
     `app.py`, `stages.py`, `requirements.txt`, `README.md`.
   - The `.streamlit` folder is hidden on some computers. It's optional; skip it if you can't see it.
   - Click **Commit changes**.

3. **Deploy on Streamlit**
   - Go to share.streamlit.io and click **Continue with GitHub**.
   - Click **Create app → Deploy a public app from GitHub**.
   - Repository: `your-username/stage-checker` · Branch: `main` · Main file path: `app.py`.
   - Optional: under **App URL**, pick a name such as `stage-checker-yourname`.
   - Click **Deploy**. The first build takes 2–4 minutes.

4. **Share the link** (it looks like `https://stage-checker-yourname.streamlit.app`).
   Friends just open it in any browser or phone. No login needed.

## Using it

- Choose **NSE** or **BSE**, then type a few letters of the symbol or company name and pick a match.
- Switch history between 2, 3 and 5 years.
- After you pick a stock, the address bar ends in `?s=SYMBOL.NS`. Copy that link to send a specific stock to someone.

## Good to know

- **Sleeping app:** free Streamlit apps sleep after a few days without visitors. The next visitor
  sees a "wake up" button and waits about 30 seconds.
- **Yahoo limits:** Yahoo Finance data is unofficial and can lag. If many people use the app at once,
  Yahoo may briefly refuse requests; the app says so, and waiting a minute fixes it. Prices are cached
  for 15 minutes to keep requests low.
- **Updating:** edit a file on GitHub (pencil icon) and commit; the app updates itself within a minute.
- **Run on your own computer instead:** install Python 3.10+, then in this folder run
  `pip install -r requirements.txt` and `streamlit run app.py`.

This is a charting aid that follows Weinstein's rules of thumb. It is not investment advice.
