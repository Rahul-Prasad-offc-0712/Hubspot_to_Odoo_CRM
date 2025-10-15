from flask import Flask, render_template, request, jsonify, send_file
import pdfkit
import io
import uuid
import base64
import requests
import datetime
from odoo_client import OdooClient

# ------------------- Flask App -------------------
app = Flask(__name__)
odoo = OdooClient()

# ------------------- HubSpot → Odoo Lead -------------------
def parse_values(values_list):
    result = {}
    for item in values_list:
        result[item["name"]] = item["value"]
    return result

def create_odoo_lead(values, lead_type="IQL"):
    name = f"{values.get('firstname','')} {values.get('lastname','')}".strip() or "Unknown"
    email = values.get("email", "No Email")
    phone = values.get("phone", "")
    city = values.get("city", "")
    lead_data = {
        "name": name,
        "email_from": email,
        "phone": phone,
        "city": city,
        "description": f"Lead from HubSpot ({lead_type})",
        "type": "opportunity",
        "stage_id": odoo._get_stage_id("New"),
        "team_id": 1
    }
    if odoo.search_lead_by_email(email):
        print(f"⚠️ Duplicate lead skipped: {name} ({email})")
        return
    lead_id = odoo.create_lead(lead_data)
    print(f"✅ Lead created: {name} ({email}), Type={lead_type}, ID={lead_id}")
    return lead_id

@app.route("/hubspot_webhook", methods=["POST"])
def hubspot_webhook():
    data = request.json
    values_list = []
    for event in data.get("events", []):
        values_list = event.get("formSubmission", {}).get("values", [])
        if values_list:
            break
    if not values_list and "properties" in data:
        values_list = [{"name": k, "value": v.get("value")} for k, v in data["properties"].items()]
    if not values_list:
        return jsonify({"status": "no data found"}), 400
    parsed = parse_values(values_list)
    create_odoo_lead(parsed, lead_type="IQL")
    return jsonify({"status": "success"})

# ------------------- Project Details -------------------
@app.route("/project/details", methods=["GET"])
def project_details():
    project_name = request.args.get("project_name")
    project_description = request.args.get("project_description")
    project_category = request.args.get("project_category")
    if not project_name or not project_description or not project_category:
        return jsonify({"status": "error", "message": "Missing parameters"}), 400
    domain = [
        ['x_studio_project_name_1', '=', project_name],
        ['x_studio_project_description_1', '=', project_description],
        ['x_studio_project_category_1', '=', project_category]
    ]
    try:
        ids = odoo.models.execute_kw(
            odoo.db, odoo.uid, odoo.password,
            'crm.lead', 'search', [domain]
        )
        if not ids:
            return jsonify({"status": "not found"})
        data = odoo.models.execute_kw(
            odoo.db, odoo.uid, odoo.password,
            'crm.lead', 'read', [ids[:1]],
            {'fields': ['name', 'x_studio_project_name_1', 'x_studio_project_description_1', 'x_studio_project_category_1']}
        )
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------------- Lead Won Check -------------------
@app.route("/lead/won", methods=["GET"])
def lead_won():
    lead_name = request.args.get("lead_name", "").strip()
    domain = [['stage_id.name', 'ilike', 'won']]
    if lead_name:
        domain.append(['name', 'ilike', lead_name])
    try:
        ids = odoo.models.execute_kw(
            odoo.db, odoo.uid, odoo.password,
            'crm.lead', 'search', [domain]
        )
        if ids:
            return jsonify({"status": "success", "message": f"Lead {lead_name or ''} is won successfully"})
        else:
            return jsonify({"status": "not found", "message": "No won lead found"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------------- RFQ Form -------------------
@app.route("/rfq/<int:lead_id>", methods=["GET"])
def rfq_form(lead_id):
    project_name = request.args.get("project_name", "")
    description = request.args.get("project_description", "")
    category = request.args.get("project_category", "")
    return render_template(
        "rfq_form.html",
        lead_id=lead_id,
        project_name=project_name,
        description=description,
        category=category
    )

@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    try:
        # ------------------ Fetch lead ------------------
        lead_id = int(request.form.get("lead_id"))
        lead = odoo.models.execute_kw(
            odoo.db, odoo.uid, odoo.password,
            'crm.lead', 'read', [[lead_id]],
            {'fields': ['name', 'partner_name', 'email_from', 'phone',
                        'x_studio_project_name_1', 'x_studio_project_description_1', 'x_studio_project_category_1']}
        )[0]

        # ------------------ Client info ------------------
        client_name = request.form.get("client_name") or lead.get('partner_name', 'Client')
        client_address = request.form.get("client_address") or ""
        client_email = request.form.get("client_email") or lead.get('email_from', 'client@example.com')
        client_phone = request.form.get("client_phone") or lead.get('phone', '')
        expiration_date = request.form.get("expiration_date") or (datetime.date.today() + datetime.timedelta(days=15)).strftime("%m/%d/%Y")

        # ------------------ Project fields ------------------
        field_names = request.form.getlist("field_name[]")
        field_values = request.form.getlist("field_value[]")
        quantities = request.form.getlist("quantity[]")
        unit_prices = request.form.getlist("unit_price[]")

        subtotal = 0
        rows = ""
        for name, value, qty, price in zip(field_names, field_values, quantities, unit_prices):
            try:
                qty_val = int(qty)
                price_val = float(price)
            except:
                qty_val = 1
                price_val = 0
            line_total = qty_val * price_val
            subtotal += line_total
            desc = f"{name}: {value}"
            rows += f"<tr><td>{qty_val}</td><td>{desc}</td><td>${price_val:.2f}</td><td>${line_total:.2f}</td></tr>"

        total = subtotal
        quotation_number = f"QT-{str(uuid.uuid4())[:8].upper()}"
        date_today = datetime.date.today().strftime("%m/%d/%Y")

        # ------------------ Logo base64 ------------------
        with open("static/logo.jpg", "rb") as img_file:
            logo_base64 = base64.b64encode(img_file.read()).decode('utf-8')

        # ------------------ PDF HTML ------------------
        pdf_html = f"""
        <html>
        <head>
        <style>
            body {{ font-family: 'Times New Roman', serif; font-size: 14px; line-height: 1.5; margin: 40px; }}
            table {{ width:100%; border-collapse: collapse; margin-top: 10px; }}
            th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
            th {{ background: #f4f4f4; }}
            .header-table td {{ border:none; vertical-align: top; }}
        </style>
        </head>
        <body>
        <table class="header-table">
            <tr>
                <td><img src="data:image/jpeg;base64,{logo_base64}" style="width:150px;height:auto;"></td>
                <td style="text-align:right;">
                    <h2>Strategic Value Solutions</h2>
                    <p>QUOTE<br>QUOTATION #: {quotation_number}<br>Date: {date_today}<br>Expiration: {expiration_date}</p>
                </td>
            </tr>
        </table>

        <h4>To:</h4>
        <p><b>{client_name}</b><br>{client_address}<br>{client_email}<br>{client_phone}</p>

        <table>
            <tr><th>Qty</th><th>Description</th><th>Unit Price</th><th>Line Total</th></tr>
            {rows}
        </table>

        <table style="margin-top:20px;">
            <tr><td style="text-align:right;"><b>Subtotal:</b></td><td style="text-align:right;">${subtotal:.2f}</td></tr>
            <tr><td style="text-align:right;"><b>Sales Tax:</b></td><td style="text-align:right;">$0.00</td></tr>
            <tr><td style="text-align:right;"><b>Total:</b></td><td style="text-align:right;"><b>${total:.2f}</b></td></tr>
        </table>

        <p style="margin-top:20px;">Quotation prepared by: <b>Uttam Soni</b></p>
        <p>This is a quotation on the goods named, subject to the conditions noted below: All sales final, payment due upon receipt.</p>
        <p>To accept this quotation, sign here and return: ________________________________________________</p>
        <p>Thank you for your business!</p>
        </body>
        </html>
        """

        # ------------------ Generate PDF ------------------
        pdf_bytes = pdfkit.from_string(pdf_html, False)

        # ------------------ Upload to Odoo ------------------
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        attachment_vals = {
            "name": f"RFQ_{quotation_number}.pdf",
            "datas": pdf_base64,
            "res_model": "crm.lead",
            "res_id": lead_id,
            "type": "binary",
            "mimetype": "application/pdf",
        }
        attachment_id = odoo.models.execute_kw(
            odoo.db, odoo.uid, odoo.password,
            "ir.attachment", "create", [attachment_vals]
        )

        # ------------------ Post message to chatter ------------------
        odoo.models.execute_kw(
            odoo.db, odoo.uid, odoo.password,
            "crm.lead", "message_post",
            [[lead_id], {
                "body": f"<p>📎 RFQ PDF generated for <b>{client_name}</b></p>",
                "message_type": "comment",
                "subtype_id": 1,
                "attachment_ids": [(4, attachment_id)],
            }]
        )

        # ------------------ Return PDF ------------------
        return send_file(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=f"RFQ_{quotation_number}.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        print(f"submit_rfq error: {e}")
        return jsonify({"error": str(e)}), 500



# ------------------- Root -------------------
@app.route("/")
def home():
    return "✅ Flask RFQ Server is running."

# ------------------- Run -------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
