frappe.ui.form.on("Subscription", {
  refresh(frm) {
    frm.add_custom_button(
      "Get Past invoices",
      function () {
   
        frm.call("generate_invoices_to_today").then((r) => {
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
