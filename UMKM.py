import importlib
import pandas as pd
import streamlit as st
import modelumkm
from auth import login_user, register_user

# Paksa Streamlit membaca versi terbaru modelumkm.py setiap kali dijalankan
importlib.reload(modelumkm)
from modelumkm import analisis, chatbot_ai

st.set_page_config(page_title="AI Penganalisis UMKM", page_icon="📊", layout="wide")

st.title("AI Penganalisis UMKM")
st.caption("Aplikasi Analisis Data Bisnis Berbasis Artificial Intelligence")


# ---------------- LOGIN / REGISTER ----------------
def halaman_auth():
    tab_login, tab_daftar = st.tabs(["Login", "Daftar"])

    with tab_login:
        with st.form("form_login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            kirim = st.form_submit_button("Login", type="primary")
        if kirim:
            berhasil, data = login_user(username, password)
            if berhasil:
                st.session_state.user = data
                st.rerun()
            else:
                st.error("Username atau password salah.")

    with tab_daftar:
        with st.form("form_daftar"):
            nama = st.text_input("Nama Lengkap")
            username = st.text_input("Username", key="reg_username")
            password = st.text_input("Password (min. 6 karakter)", type="password", key="reg_pw")
            konfirmasi = st.text_input("Konfirmasi Password", type="password")
            kirim = st.form_submit_button("Daftar", type="primary")
        if kirim:
            berhasil, pesan = register_user(username, nama, password, konfirmasi)
            if berhasil:
                st.success(pesan)
            else:
                st.error(pesan)


if st.session_state.get("user") is None:
    halaman_auth()
    st.stop()

with st.sidebar:
    st.write(f"Masuk sebagai **{st.session_state.user['nama']}**")
    if st.button("Logout"):
        for key in ("user", "chat_history", "hasil", "hasil_kunci", "chat_kunci"):
            st.session_state.pop(key, None)
        st.rerun()


# ---------------- APLIKASI UTAMA ----------------
file = st.file_uploader("Upload Data UMKM / Pembukuan (Format Excel/CSV)", type=["xlsx", "csv"])

if file is not None:
    sheet = "-"
    if file.name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        xls = pd.ExcelFile(file)
        daftar_sheet = xls.sheet_names

        prioritas = ["Penjualan", "Data UMKM", "Produk", "Pengeluaran"]
        awal = 0
        for p in prioritas:
            if p in daftar_sheet:
                awal = daftar_sheet.index(p)
                break

        if len(daftar_sheet) > 1:
            sheet = st.selectbox("Pilih sheet data yang ingin dianalisis", daftar_sheet, index=awal)
        else:
            sheet = daftar_sheet[0]

        df = xls.parse(sheet)

    if sheet in ["Hari Ini", "Ringkasan", "Daftar", "Harga Bahan", "Resep"]:
        st.warning(f"Sheet '{sheet}' berisi ringkasan rumus atau daftar acuan. Disarankan memilih sheet **Penjualan**, **Produk**, atau **Pengeluaran**.")

    st.write("**Kolom pada data:**", ", ".join(df.columns.tolist()))
    st.dataframe(df, use_container_width=True, height=260)

    kunci = f"{file.name}|{sheet}"

    if st.button("Mulai Analisis AI", type="primary"):
        try:
            st.session_state.hasil = analisis(df)
            st.session_state.hasil_kunci = kunci
        except ValueError as e:
            st.session_state.hasil = None
            st.error(str(e))

    if st.session_state.get("hasil") and st.session_state.get("hasil_kunci") == kunci:
        st.subheader(f"Hasil Analisis AI (Sheet: {sheet})")
        for h in st.session_state.hasil:
            if "terendah" in h or "Perhatikan" in h:
                st.error(h)
            elif "Pertimbangkan" in h or "menaikkan" in h or "tekan HPP" in h:
                st.warning(h)
            elif "Prioritaskan" in h or "Restock" in h or "Fokuskan" in h or "Maksimalkan" in h:
                st.info(h)
            else:
                st.success(h)

    st.divider()
    st.subheader(f"Tanya AI tentang Sheet '{sheet}'")
    st.caption("Ajukan pertanyaan terkait data transaksi pada sheet ini.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    if st.session_state.get("chat_kunci") != kunci:
        st.session_state.chat_history = []
        st.session_state.chat_kunci = kunci

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if prompt := st.chat_input(f"Contoh: Apa rekomendasi perbaikan untuk sheet {sheet}?"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("AI sedang menganalisis..."):
                reply = chatbot_ai(df, st.session_state.chat_history)
            st.write(reply)

        st.session_state.chat_history.append({"role": "assistant", "content": reply})

    if st.session_state.chat_history:
        if st.button("Hapus Riwayat Chat", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()