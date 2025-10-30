# 📱 Mobile Dashboard Guide

## Access Your Dashboard

Your QX Algo dashboard is now live on Railway and accessible from any device!

### 🌐 Dashboard URL

Your dashboard URL will be:
```
https://your-railway-app.up.railway.app/
```

**To find your exact URL:**
1. Go to [railway.app](https://railway.app)
2. Open your QX_Algo project
3. Click on your deployment
4. Find the "Domains" section
5. Your URL is shown there (looks like `qx-algo-production.up.railway.app`)

**Bookmark this URL on your phone!**

---

## 📊 Dashboard Features

### Status Card
- **🟢 Green Dot** = Algo is running
- **🔴 Red Dot** = Algo is stopped
- **Session Badge** = Current active session (ODR/RDR/ADR/NONE)
- **DR/IDR Levels** = Current day's range boundaries

### Performance Metrics
- **P&L** = Today's total profit/loss
- **Trades** = Number of trades today
- **Wins** = Winning trades count
- **Losses** = Losing trades count

### Recent Trades List
- Last 10 trades of the day
- Shows: Time, Session, Bias, Entry, Stop, Size
- Color-coded: 🟢 Bullish | 🔴 Bearish

### Auto-Refresh
- Updates every 10 seconds automatically
- Shows last update timestamp
- No need to manually refresh

---

## 📱 Mobile Usage Tips

### Save to Home Screen (iOS)
1. Open dashboard in Safari
2. Tap the Share button
3. Select "Add to Home Screen"
4. Name it "QX Algo"
5. Tap "Add"

Now you have a native-feeling app icon!

### Save to Home Screen (Android)
1. Open dashboard in Chrome
2. Tap the menu (3 dots)
3. Select "Add to Home screen"
4. Name it "QX Algo"
5. Tap "Add"

### Lock Screen Widget (Advanced)
For iOS 16+, you can add a widget to your lock screen:
1. Use Shortcuts app to create a widget
2. Link it to your dashboard URL
3. See status at a glance without unlocking

---

## 🔍 What to Monitor

### During Trading Hours (4am-8am, 10:30am-4pm, 8:30pm-1am)

**Look for:**
- ✅ Green dot (algo running)
- ✅ Correct session displayed (ODR/RDR/ADR)
- ✅ DR/IDR levels showing
- ✅ Auto-refresh working (timestamp updates every 10s)

**Red flags:**
- 🚨 Red dot for more than 2 minutes
- 🚨 "NONE" session during trading hours
- 🚨 No DR/IDR levels showing
- 🚨 Timestamp not updating (stale data)

### Outside Trading Hours

**Normal behavior:**
- Session badge shows "NONE"
- DR/IDR may not be displayed
- Algo still running (green dot)
- Recent trades from earlier sessions visible

---

## 📈 Example Screenshots

### Healthy Running State
```
🤖 Algo Status
🟢 Running          [RDR 10:30-16:00]
DR: 6952.00/6945.00 | IDR: 6950.00/6948.00

💰 Today's Performance
P&L: $+250.00    Trades: 3
Wins: 2          Losses: 1

📈 Recent Trades
10:35:15  BULLISH
RDR | Entry: 6949.60 | Stop: 6947.00 | Size: 1

13:42:30  BEARISH
RDR | Entry: 6950.40 | Stop: 6953.00 | Size: 1
```

### Waiting State (No Trades Yet)
```
🤖 Algo Status
🟢 Running          [ODR 04:00-08:00]
DR: 6952.00/6945.00 | IDR: 6950.00/6948.00

💰 Today's Performance
P&L: $0.00       Trades: 0
Wins: 0          Losses: 0

📈 Recent Trades
No trades yet today
```

---

## 🆘 Troubleshooting

### Dashboard Won't Load
1. Check Railway deployment status
2. Verify you're using the correct URL
3. Check if Railway is experiencing downtime
4. Try accessing from a different network

### Dashboard Shows "Stopped" But Should Be Running
1. Check Railway logs
2. Algo may have crashed (check error logs)
3. Restart deployment on Railway
4. Contact support if persistent

### Data Not Updating
1. Check "Last updated" timestamp
2. If stale > 2 minutes, algo may be stuck
3. Check Railway logs for errors
4. Refresh browser completely

### Trades Not Showing
1. Check trade_log.csv exists
2. Verify trades were actually placed
3. Dashboard only shows TODAY's trades
4. May need to wait for first trade

---

## 🔐 Security Notes

### URL Privacy
- Your dashboard URL is public but not easily guessable
- No authentication required (for ease of access)
- Only shows trading data, cannot control algo
- Consider keeping URL private

### Data Displayed
- Read-only view of algo status
- Cannot place/cancel trades from dashboard
- Cannot modify algo settings
- Safe to share with trusted parties

---

## 🎨 Dashboard Design

### Color Scheme
- **Purple Gradient Background** = Modern, professional
- **White Cards** = Clean, easy to read
- **Green** = Positive (running, wins, positive P&L)
- **Red** = Negative (stopped, losses, negative P&L)
- **Blue/Yellow/Green Badges** = Session types (ODR/RDR/ADR)

### Mobile-First Design
- Optimized for phone screens (320px+)
- Touch-friendly buttons/cards
- Large, readable fonts
- Minimal scrolling needed
- Works in portrait/landscape

---

## 🔄 Updates & Maintenance

### Dashboard Updates Automatically
- No app store updates needed
- Changes deploy with algo updates
- Always shows latest data format
- Compatible with all mobile browsers

### Data Retention
- Recent trades: Last 10 trades of current day
- Resets at midnight Eastern Time
- Historical data in trade_log.csv (on server)
- P&L resets daily

---

## 📞 Support

### If Dashboard Stops Working
1. Check Railway deployment logs
2. Verify algo is still running
3. Check for recent code changes
4. Restart Railway deployment

### Feature Requests
Want to add:
- Push notifications for trades?
- Historical P&L chart?
- Win rate analytics?
- Custom alerts?

Let me know what would be useful!

---

## ✅ Quick Checklist

Before relying on dashboard:
- [ ] Bookmark Railway URL on phone
- [ ] Add to home screen for quick access
- [ ] Test auto-refresh (watch timestamp)
- [ ] Verify trades appear after execution
- [ ] Check during all 3 sessions (ODR/RDR/ADR)
- [ ] Test on WiFi and cellular data

---

## 🎯 Best Practices

1. **Check morning before ODR** (3:50am) to ensure algo ready
2. **Glance during RDR** (10:30am-4pm) for confirmation
3. **Monitor ADR start** (8:25pm) for evening session
4. **Review end of day** to see full trade log
5. **Bookmark for easy access** from any device

---

Your algo now has 24/7 monitoring accessible from anywhere! 📱✨

