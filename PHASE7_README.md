# OM KIRANA STORE — Phase 7

New features:
- Smart product search by name/description/barcode
- Barcode lookup
- Advanced sales report
- Top-selling products
- Low-stock report
- Loyalty points API (1 point per ₹100 spent)
- Demo coupon system: WELCOME10, SAVE50, OM20
- Smart Tools page
- Phase 1–6 retained

Run:
pip install -r requirements.txt
python app.py

Customer: http://127.0.0.1:5000
Smart Tools: http://127.0.0.1:5000/smart-tools
Admin: http://127.0.0.1:5000/admin/login

Note:
Barcode lookup expects a barcode value to be stored for a product. The current scanner UI is a lookup field; camera-based scanning can be added in a later phase.
Coupons and loyalty are demo business rules and should be configured for the real store.
