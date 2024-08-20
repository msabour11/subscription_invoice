frappe.ui.form.on("Subscription", {
  refresh(frm) {
    frm.add_custom_button(
      "Get Past invoices",
      function () {
        frm.call("fetch_past_subscription_invoices").then((r) => {
          if (!r.exec) {
            frm.reload_doc();
            console.log("invoices", r.message);
          }
        });
      },
      "Actions"
    );
  },
});
