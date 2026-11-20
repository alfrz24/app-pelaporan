/**
 * main.js - Client-side script for App Pelaporan
 * Mengatur interaktivitas UI, Sidebar toggle, pencarian real-time, filter status, dan toast notifikasi.
 */

document.addEventListener('DOMContentLoaded', function () {
  'use strict';

  // ==========================================
  // 1. SIDEBAR TOGGLE (DESKTOP & MOBILE)
  // ==========================================
  const sidebarToggleBtn = document.getElementById('sidebarToggle');
  const sidebarBackdrop = document.getElementById('sidebarBackdrop');
  const body = document.body;

  if (sidebarToggleBtn) {
    sidebarToggleBtn.addEventListener('click', function () {
      if (window.innerWidth >= 992) {
        // Mode Desktop: Collapse sidebar ke versi mini icon
        body.classList.toggle('sidebar-collapsed');
      } else {
        // Mode Mobile: Slide in/out sidebar dengan backdrop
        body.classList.toggle('sidebar-mobile-show');
      }
    });
  }

  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener('click', function () {
      body.classList.remove('sidebar-mobile-show');
    });
  }

  // Auto-close mobile sidebar ketika window di-resize ke ukuran besar
  window.addEventListener('resize', function () {
    if (window.innerWidth >= 992) {
      body.classList.remove('sidebar-mobile-show');
    }
  });

  // ==========================================
  // 2. LIVE SEARCH FILTER PADA TABEL
  // ==========================================
  const searchInput = document.getElementById('tableSearchInput');
  const tableRows = document.querySelectorAll('#laporanTable tbody tr');

  if (searchInput && tableRows.length > 0) {
    searchInput.addEventListener('input', function (e) {
      const query = e.target.value.toLowerCase().trim();

      tableRows.forEach(row => {
        const textContent = row.textContent.toLowerCase();
        if (textContent.includes(query)) {
          row.style.display = '';
        } else {
          row.style.display = 'none';
        }
      });
    });
  }

  // ==========================================
  // 3. FILTER BY STATUS LAPORAN
  // ==========================================
  const statusFilter = document.getElementById('statusFilter');

  if (statusFilter && tableRows.length > 0) {
    statusFilter.addEventListener('change', function () {
      const selectedStatus = this.value.toLowerCase();

      tableRows.forEach(row => {
        const statusBadge = row.querySelector('.badge-status');
        if (!statusBadge) return;

        const rowStatus = statusBadge.textContent.toLowerCase().trim();

        if (selectedStatus === 'all' || rowStatus.includes(selectedStatus)) {
          row.style.display = '';
        } else {
          row.style.display = 'none';
        }
      });
    });
  }

  // ==========================================
  // 4. FORM MODAL SUBMIT & TOAST NOTIFICATION
  // ==========================================
  const formTambahLaporan = document.getElementById('formTambahLaporan');
  const modalLaporanElement = document.getElementById('modalTambahLaporan');

  if (formTambahLaporan) {
    formTambahLaporan.addEventListener('submit', function (e) {
      // Jika form menggunakan Django POST biasa, biarkan submit.
      // Di sini kita sediakan validasi visual Bootstrap & demo toast jika AJAX/preview:
      if (!this.checkValidity()) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.add('was-validated');
        return;
      }

      // Demo feedback jika preview mandiri:
      if (!this.getAttribute('action') || this.getAttribute('action') === '#') {
        e.preventDefault();

        // Tutup modal
        if (modalLaporanElement) {
          const modalInstance = bootstrap.Modal.getInstance(modalLaporanElement);
          if (modalInstance) modalInstance.hide();
        }

        // Tampilkan Toast Notifikasi
        showToast('Sukses!', 'Laporan bulanan baru berhasil disimpan ke database.', 'success');
        formTambahLaporan.reset();
        formTambahLaporan.classList.remove('was-validated');
      }
    });
  }

  // ==========================================
  // 5. HELPER FUNCTION: TOAST NOTIFIKASI
  // ==========================================
  function showToast(title, message, type = 'primary') {
    const toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) return;

    const iconClass = type === 'success' ? 'bi-check-circle-fill text-success' : 'bi-info-circle-fill text-primary';

    const toastHtml = `
      <div class="toast align-items-center border-0 shadow-lg mb-2" role="alert" aria-live="assertive" aria-atomic="true">
        <div class="d-flex">
          <div class="toast-body d-flex align-items-center gap-2">
            <i class="bi ${iconClass} fs-5"></i>
            <div>
              <strong>${title}</strong>
              <div class="small text-muted">${message}</div>
            </div>
          </div>
          <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      </div>
    `;

    const wrapper = document.createElement('div');
    wrapper.innerHTML = toastHtml.trim();
    const toastElement = wrapper.firstChild;

    toastContainer.appendChild(toastElement);
    const toastInstance = new bootstrap.Toast(toastElement, { delay: 4000 });
    toastInstance.show();

    toastElement.addEventListener('hidden.bs.toast', () => {
      toastElement.remove();
    });
  }

  // Expose showToast secara global agar bisa dipanggil di mana saja jika dibutuhkan
  window.showToast = showToast;

  // Inisialisasi semua Bootstrap Tooltip jika ada
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
});
