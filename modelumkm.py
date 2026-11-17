import os
import re
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# Pengenalan kolom otomatis
# Mendukung dataset lama & format pembukuan_usaha (1) baru.xlsx
# ------------------------------------------------------------------
ALIAS = {
    "omzet": ["order_value_EUR", "Omzet per Bulan (Rp)", "omzet", "revenue", "sales", "penjualan", "total penjualan (rp)", "harga jual (rp)", "total omzet (rp)"],
    "biaya": ["cost", "Biaya Operasional per Bulan (Rp)", "biaya operasional", "biaya", "hpp", "hpp total (rp)", "hpp per satuan (rp)", "jumlah (rp)"],
    "laba": ["Laba per Bulan (Rp)", "laba", "profit", "laba kotor (rp)", "laba per satuan (rp)", "laba bersih (rp)"],
    "kategori": ["category", "Sektor Usaha", "kategori", "sektor", "channel", "hari", "kategori pengeluaran"],
    "produk": ["Produk Utama", "product", "produk", "nama produk"],
    "wilayah": ["country", "Provinsi", "Kota/Kabupaten", "negara", "wilayah", "metode bayar", "lokasi"],
}

def _norm(teks):
    return re.sub(r"[^a-z0-9]", "", str(teks).lower())

def _cari(df, daftar):
    peta = {_norm(c): c for c in df.columns}
    for alias in daftar:
        if _norm(alias) in peta:
            return peta[_norm(alias)]
    return None

def cari_kolom(df, kunci):
    return _cari(df, ALIAS[kunci])

def _angka(x, desimal=1):
    s = f"{x:,.{desimal}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def _fmt(nilai, mu):
    a, tanda = abs(nilai), ("-" if nilai < 0 else "")
    if mu == "EUR":
        return f"{tanda}€{_angka(a, 0)}"
    for batas, satuan in ((1e12, "triliun"), (1e9, "miliar"), (1e6, "juta")):
        if a >= batas:
            return f"{tanda}Rp {_angka(a / batas, 1)} {satuan}"
    return f"{tanda}Rp {_angka(a, 0)}"

def _siapkan(df):
    """Bersihkan data & kembalikan (df_bersih, peta_kolom, mata_uang). df asli tidak diubah."""
    d = df.copy()
    
    # Pre-processing untuk sheet "Produk" jika omzet absolut tidak ada 
    # (hitung Total Penjualan dari Total Terjual * Harga Jual)
    if "Total Terjual" in d.columns and "Harga Jual (Rp)" in d.columns and not _cari(d, ["Total Penjualan (Rp)", "Omzet"]):
        d["Total Penjualan (Rp)"] = pd.to_numeric(d["Total Terjual"], errors="coerce") * pd.to_numeric(d["Harga Jual (Rp)"], errors="coerce")
        if "HPP per Satuan (Rp)" in d.columns:
            d["HPP Total (Rp)"] = pd.to_numeric(d["Total Terjual"], errors="coerce") * pd.to_numeric(d["HPP per Satuan (Rp)"], errors="coerce")

    k = {nama: cari_kolom(d, nama) for nama in ALIAS}

    # Kasus 1: Memiliki Data Pemasukan/Omzet (contoh: sheet Penjualan, Produk)
    if k["omzet"]:
        d["_omzet"] = pd.to_numeric(d[k["omzet"]], errors="coerce")
        if k["biaya"]:
            d["_biaya"] = pd.to_numeric(d[k["biaya"]], errors="coerce")
            d["_laba"] = d["_omzet"] - d["_biaya"]
        elif k["laba"]:
            d["_laba"] = pd.to_numeric(d[k["laba"]], errors="coerce")
            d["_biaya"] = d["_omzet"] - d["_laba"]
        else:
            d["_biaya"] = 0
            d["_laba"] = d["_omzet"]
            
        d = d.dropna(subset=["_omzet"])
        d = d[d["_omzet"] > 0]
        
    # Kasus 2: Hanya memiliki data Pengeluaran (contoh: sheet Pengeluaran)
    elif k["biaya"]:
        d["_omzet"] = 0
        d["_laba"] = 0
        d["_biaya"] = pd.to_numeric(d[k["biaya"]], errors="coerce")
        d = d.dropna(subset=["_biaya"])
        d = d[d["_biaya"] > 0]
        
    else:
        raise ValueError(
            "Kolom data tidak dikenali. Pilih sheet yang memuat data Penjualan, Produk, atau Pengeluaran. "
            f"Kolom yang ada: {', '.join(map(str, d.columns))}"
        )

    if d.empty:
        raise ValueError("Tidak ada baris data valid (angka harus lebih dari 0).")

    d["_margin"] = 0.0
    mask = d["_omzet"] > 0
    d.loc[mask, "_margin"] = (d.loc[mask, "_laba"] / d.loc[mask, "_omzet"]) * 100

    mu = "EUR" if (k["omzet"] and "eur" in _norm(k["omzet"])) else "Rp"
    return d, k, mu

def _persen_tidak(d, kolom):
    return (d[kolom].astype(str).str.strip().str.lower() == "tidak").mean() * 100


# ------------------------------------------------------------------
# Analisis otomatis
# ------------------------------------------------------------------
def analisis(df):
    d, k, mu = _siapkan(df)
    hasil = []

    # Jika hanya ada data pengeluaran (Sheet Pengeluaran)
    if d["_omzet"].sum() == 0 and d["_biaya"].sum() > 0:
        hasil.append(f"Total pengeluaran yang tercatat sebesar {_fmt(d['_biaya'].sum(), mu)}.")
        if k["kategori"]:
            per_kat = d.groupby(k["kategori"])["_biaya"].sum()
            if not per_kat.empty:
                hasil.append(f"Perhatikan! Pengeluaran terbesar ada pada '{per_kat.idxmax()}' ({_fmt(per_kat.max(), mu)}). Evaluasi pengeluaran ini.")
        return hasil

    # Analisis standar (Ada Omzet/Penjualan)
    if k["kategori"]:
        per_kat = d.groupby(k["kategori"])["_omzet"].sum()
        if not per_kat.empty:
            label_kat = "Kategori/Channel" if _norm(k["kategori"]) in ("kategori", "category", "channel") else k["kategori"]
            hasil.append(f"Prioritaskan {label_kat} '{per_kat.idxmax()}' (total kontribusi {_fmt(per_kat.max(), mu)}).")
            hasil.append(
                f"Perhatikan! Kontribusi terendah ada pada {label_kat} '{per_kat.idxmin()}' "
                f"({_fmt(per_kat.min(), mu)}). Evaluasi kembali strateginya."
            )

    kol_produk = k["produk"]
    if kol_produk:
        per_produk = d.groupby(kol_produk)["_omzet"].sum()
        if not per_produk.empty:
            hasil.append(f"Restock atau fokus pada produk '{per_produk.idxmax()}' karena angka penjualannya paling tinggi.")

    margin = d["_margin"].mean()
    if margin > 20:
        hasil.append(f"Harga dan laba cukup sehat. Pertahankan (rata-rata margin {_angka(margin)}%).")
    elif margin > 0:
        hasil.append(f"Pertimbangkan menaikkan harga atau tekan HPP (rata-rata margin hanya {_angka(margin)}%).")

    rugi = int((d["_laba"] < 0).sum())
    if rugi:
        hasil.append(
            f"Perhatikan! {rugi} dari {len(d)} data transaksi ({_angka(rugi / len(d) * 100)}%) "
            f"mengalami kerugian (margin negatif). Segera tinjau rincian biaya atau HPP."
        )

    if k["wilayah"]:
        per_w = d.groupby(k["wilayah"])["_omzet"].sum()
        if not per_w.empty:
            label = "Metode / Wilayah" if _norm(k["wilayah"]) in ("metode bayar", "country", "negara", "wilayah") else k["wilayah"]
            hasil.append(
                f"{label} paling populer: '{per_w.idxmax()}' ({_fmt(per_w.max(), mu)}). "
                f"Maksimalkan layanan pada opsi ini."
            )

    # Insight tambahan khusus dataset UMKM lama
    kol_qris = _cari(d, ["Terima QRIS"])
    if kol_qris:
        p = _persen_tidak(d, kol_qris)
        if p >= 10:
            hasil.append(f"Pertimbangkan mengaktifkan pembayaran QRIS: {_angka(p)}% belum menerimanya.")

    kol_nib = _cari(d, ["Memiliki NIB"])
    if kol_nib:
        p = _persen_tidak(d, kol_nib)
        if p >= 10:
            hasil.append(f"Pertimbangkan mendorong pengurusan NIB untuk legalitas ({_angka(p)}% belum memiliki).")

    return hasil


# ------------------------------------------------------------------
# Chatbot Gemini
# ------------------------------------------------------------------
def _ambil_api_key():
    for nama in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        nilai = os.getenv(nama)
        if nilai:
            return nilai
    try:
        import streamlit as st
        for nama in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if nama in st.secrets:
                return st.secrets[nama]
    except Exception:
        pass
    return None


def _konteks_data(df):
    baris = [
        f"- Kolom tersedia: {', '.join(map(str, df.columns))}",
        f"- Total baris: {len(df)}",
    ]
    try:
        d, k, mu = _siapkan(df)
        if d["_omzet"].sum() > 0:
            baris.append(
                f"- Total omzet: {_fmt(d['_omzet'].sum(), mu)}, total biaya/HPP: {_fmt(d['_biaya'].sum(), mu)}, total laba: {_fmt(d['_laba'].sum(), mu)}, "
                f"rata-rata margin: {_angka(d['_margin'].mean())}%, transaksi rugi: {int((d['_laba'] < 0).sum())}"
            )
            for kunci in ("kategori", "produk", "wilayah"):
                kol = k[kunci]
                if kol:
                    g = (d.groupby(kol).agg(omzet=("_omzet", "sum"), laba=("_laba", "sum"))
                           .sort_values("omzet", ascending=False).head(10))
                    isi = "; ".join(
                        f"{i}: omzet {_fmt(r.omzet, mu)}, laba {_fmt(r.laba, mu)}" for i, r in g.iterrows()
                    )
                    baris.append(f"- 10 teratas {kol}: {isi}")
        else:
            baris.append(f"- Total pengeluaran/biaya: {_fmt(d['_biaya'].sum(), mu)}")
            if k["kategori"]:
                g = d.groupby(k["kategori"])["_biaya"].sum().sort_values(ascending=False).head(10)
                isi = "; ".join(f"{i}: {_fmt(v, mu)}" for i, v in g.items())
                baris.append(f"- 10 pengeluaran teratas ({k['kategori']}): {isi}")
                
    except ValueError:
        pass

    for c in df.select_dtypes(include="number").columns:
        s = df[c].dropna()
        if len(s):
            baris.append(f"- {c}: rata-rata {s.mean():,.2f}, median {s.median():,.2f}, min {s.min():,.2f}, max {s.max():,.2f}")
    
    for c in df.select_dtypes(exclude="number").columns:
        if df[c].nunique() <= 15:
            baris.append(f"- Sebaran {c}: {df[c].value_counts().to_dict()}")

    return "\n".join(baris) + f"\n\nPreview data:\n{df.head(3).to_string(index=False)}"


def chatbot_ai(df, messages):
    api_key = _ambil_api_key()
    if not api_key:
        return ("API key Gemini belum diatur. Buat file .env berisi "
                "GEMINI_API_KEY=kunci_kamu, lalu jalankan ulang aplikasi.")

    genai.configure(api_key=api_key)

    system_instruction = f"""Kamu adalah AI Advisor untuk Bisnis UMKM.
Kamu membantu pengguna memahami data bisnis mereka dan memberikan saran praktis.

Data yang sedang dianalisis:
{_konteks_data(df)}

Aturan menjawab:
- Jawab berdasarkan data di atas jika pertanyaan berkaitan dengan data
- Gunakan bahasa Indonesia yang sederhana, ramah, dan solutif
- Jawab singkat dan langsung ke intinya (maksimal 3-4 kalimat)
- Pahami bahwa data bisa berasal dari sheet Penjualan, Produk, Pengeluaran, atau dataset UMKM gabungan
"""

    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_instruction,
        )

        gemini_history = []
        for msg in messages[:-1]:
            gemini_history.append({
                "role": "model" if msg["role"] == "assistant" else "user",
                "parts": [msg["content"]],
            })

        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(messages[-1]["content"])
        return response.text
    except Exception as e:
        return f"Maaf, AI belum bisa menjawab saat ini ({type(e).__name__}). Cek API key / koneksi, lalu coba lagi."