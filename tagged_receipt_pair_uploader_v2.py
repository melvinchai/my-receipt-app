# Replace this block inside your "Upload Receipt Pair" section

if receipt_file and payment_file:
    st.markdown("---")
    st.subheader("🖼️ Combined Preview")

    grayscale = st.toggle("🖤 Convert preview to grayscale", value=False)

    preview_img = generate_preview(receipt_file, payment_file, claimant_id)
    if grayscale:
        preview_img = preview_img.convert("L")

    st.image(preview_img, caption="🧾 Combined Receipt + Payment Proof", use_container_width=True)

    pdf_buf = convert_image_to_pdf(preview_img)
    st.download_button("📥 Download Combined PDF", pdf_buf, "receipt_pair.pdf", "application/pdf")

    receipt_doc = process_document(receipt_file.getvalue(), "image/jpeg")
    payment_doc = process_document(payment_file.getvalue(), "image/jpeg")

    receipt_row = extract_fixed_fields(receipt_doc, source="receipt")
    payment_row = extract_fixed_fields(payment_doc, source="payment")

    receipt_row["Type"] = "receipt"
    payment_row["Type"] = "payment"

    combined_df = pd.DataFrame([receipt_row, payment_row])
    combined_df = combined_df[["Type", "merchant_name", "date", "total", "reference_number"]]

    # 🧮 Reconciliation logic
    try:
        r_total = receipt_row["total"].replace(",", "").replace("RM", "").strip()
        p_total = payment_row["total"].replace(",", "").replace("RM", "").strip()
        if float(r_total) == float(p_total):
            st.success(f"✅ Amounts match: RM {r_total}")
        else:
            st.warning(f"⚠️ Mismatch: Receipt shows RM {r_total}, payment shows RM {p_total}")
    except:
        st.info("ℹ️ Unable to compare amounts—missing or non-numeric values")

    st.subheader("📊 Summary Table")
    st.dataframe(combined_df, use_container_width=True)

    csv_buf = combined_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download Summary CSV", csv_buf, "receipt_summary.csv", "text/csv")

    # ✅ Upload only if parsing succeeded
    if receipt_doc.entities and payment_doc.entities:
        receipt_blob_path = upload_to_gcs(receipt_file, f"{tag_id}_receipt.jpg")
        payment_blob_path = upload_to_gcs(payment_file, f"{tag_id}_payment.jpg")
        st.success(f"✅ Receipt uploaded to `{receipt_blob_path}`")
        st.success(f"✅ Payment proof uploaded to `{payment_blob_path}`")
    else:
        st.warning("⚠️ Upload skipped—no entities extracted from one or both documents.")

    # 🧠 Trace extracted fields
    st.markdown("---")
    st.subheader("🧠 Processor Field Trace")

    st.markdown("**Receipt Fields Extracted:**")
    st.dataframe(trace_all_fields(receipt_doc), use_container_width=True)

    st.markdown("**Payment Fields Extracted:**")
    st.dataframe(trace_all_fields(payment_doc), use_container_width=True)
