"""Penyimpanan tanda tangan digital berbasis database (kompatibel dengan hosting serverless)."""
from .models import TandaTangan


def nama_pegawai(pegawai_id):
    return f'pegawai_{int(pegawai_id)}.png'


def nama_pejabat(role):
    return f'pejabat_{role}.png'


def ambil(nama_berkas):
    """Kembalikan bytes PNG atau None bila belum ada."""
    row = TandaTangan.objects.filter(nama_berkas=nama_berkas).values_list('data', flat=True).first()
    return bytes(row) if row is not None else None


def simpan(nama_berkas, data):
    TandaTangan.objects.update_or_create(nama_berkas=nama_berkas, defaults={'data': data})


def hapus(nama_berkas):
    return TandaTangan.objects.filter(nama_berkas=nama_berkas).delete()[0] > 0


def daftar_ada():
    """Himpunan nama berkas yang tersedia (satu query)."""
    return set(TandaTangan.objects.values_list('nama_berkas', flat=True))
