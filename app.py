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


# ------------------- Submit RFQ & Generate PDF -------------------
@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    try:
        lead_id = int(request.form.get("lead_id"))
        client_name = request.form.get("client_name")
        client_email = request.form.get("client_email")
        client_phone = request.form.get("client_phone")
        project_name = request.form.get("project_name")
        project_description = request.form.get("project_description")
        project_category = request.form.get("project_category")
        quotation_number = f"QT-{str(uuid.uuid4())[:8].upper()}"
        date_today = datetime.date.today().strftime("%m/%d/%Y")

        # ---------------- Prepare HTML PDF ----------------
        html_content = render_template(
            "rfq_pdf_template.html",
            quotation_number=quotation_number,
            client_name=client_name,
            client_email=client_email,
            client_phone=client_phone,
            project_name=project_name,
            project_description=project_description,
            project_category=project_category,
            date_today=date_today
        )
        pdf_data = pdfkit.from_string(html_content, False)

        # ---------------- Upload PDF to Odoo Chatter ----------------
        pdf_base64 = base64.b64encode(pdf_data).decode("utf-8")
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

        # Post message in chatter
        odoo.models.execute_kw(
            odoo.db, odoo.uid, odoo.password,
            "crm.lead", "message_post",
            [[lead_id], {
                "body": f"<p>📎 RFQ PDF generated for <b>{project_name}</b></p>",
                "message_type": "comment",
                "subtype_id": 1,
                "attachment_ids": [(4, attachment_id)],
            }]
        )

        # ---------------- SmartArch Integration ----------------
        smartarch_payload = {
            "userEmail": client_email,
            "userName": client_name,
            "orgName": project_name,
            "orgType": project_category,
            "orgEmployeesCount": "1-50",
            "orgDescription": project_description,
            "orgContactInfo": f"Phone: {client_phone}, Email: {client_email}",
        }
        try:
            smartarch_response = requests.post(
                "http://localhost:8001/api/organization/create-user-organization",
                json=smartarch_payload, timeout=10
            )
            print(f"SmartArch Response: {smartarch_response.text}")
        except Exception as e:
            print(f"SmartArch API call failed: {e}")

        # ---------------- Return PDF ----------------
        return send_file(
            io.BytesIO(pdf_data),
            as_attachment=True,
            download_name=f"RFQ_{quotation_number}.pdf",
            mimetype="application/pdf",
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
