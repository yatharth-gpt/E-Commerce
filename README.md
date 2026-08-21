# OM KIRANA STORE — PHASE 9
## Professional Store Upgrade

Phase 9 turns the previous project into a practical local-store management system.

### Customer side
- Smart homepage search by name/category/barcode
- Voice search
- Camera barcode scanner using browser BarcodeDetector where supported
- Manual barcode fallback
- Category browsing
- Product details, description, offer and stock
- Wishlist / favourites
- Cart quantity controls
- Reorder from previous orders
- Reviews & ratings
- Related products
- Offers and coupon codes
- Loyalty points: 1 point per ₹100 order value
- Pickup / home delivery
- Pay at Store / UPI selection
- Order tracking + status history
- Invoice PDF
- Customer login/profile
- Mobile-first responsive UI
- PWA install support retained

### Owner / Admin
Open `/admin/login`.
Demo login:
- Username: `admin`
- Password: `admin123`

Features:
- Dashboard with sales, gross profit, expenses and net profit
- 7-day sales view
- Low-stock list
- New-order notifications
- Product add form with:
  Name, category, purchase price, selling price, stock, barcode, image, description, offer
- Product automatically appears on customer side after saving
- Bulk price + stock update
- Inventory management
- Low/out-of-stock management
- Order management + status updates
- Customer management
- Review management
- Offer management
- Coupon management
- Expense management
- Best-selling product report
- Sales history
- Orders/products CSV reports (Excel-compatible)
- Invoice generation
- Store QR generation
- Store settings: address, phone, WhatsApp, UPI ID, delivery charge, opening/closing time, low-stock limit

### Run
1. Extract this ZIP.
2. Open the extracted folder in VS Code.
3. Open Terminal in that folder.
4. Run:
   `pip install -r requirements.txt`
5. Run:
   `python app.py`
6. Open:
   `http://127.0.0.1:5000`
7. Owner panel:
   `http://127.0.0.1:5000/admin/login`

The SQLite database is created automatically in `database/om_kirana.db`.

### Important
- This is a portfolio/local-store application. For real public customers, deploy it on an HTTPS host.
- Camera access normally requires HTTPS (localhost is also allowed by modern browsers).
- Selecting UPI only records the chosen payment method; it does not automatically collect money. Real UPI collection needs a verified payment gateway/merchant integration.
- WhatsApp/SMS notifications require official provider integration.
- Change the demo admin password and Flask secret key before public deployment.
- Enter real purchase prices in Product Management for meaningful profit calculations.
