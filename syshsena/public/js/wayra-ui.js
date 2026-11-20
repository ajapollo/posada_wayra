/* ============================================================================
   POSADA WAYRA · Interfaz Interactiva y Lógica de Reserva
   ============================================================================
   ÍNDICE DE BÚSQUEDA RÁPIDA (Usa Ctrl + F con estas etiquetas):
   - [MÓDULO: CONFIGURACIÓN Y PALETA DE COLORES]
   - [MÓDULO: FORMATO MONETARIO Y VALIDADORES]
   - [MÓDULO: ALERTAS Y DIÁLOGOS SWEETALERT2]
   - [MÓDULO: ACCIONES GENERALES Y CONFIRMACIONES]
   - [MÓDULO: CONTROL DE CHECK-OUT Y SALDOS PENDIENTES]
   - [MÓDULO: POLÍTICA DE NO-SHOW]
   - [MÓDULO: SELECTOR DE HUÉSPEDES - LÍMITES DEL CATÁLOGO]
   - [MÓDULO: CALENDARIO DE 2 MESES Y TARIFAS DINÁMICAS]
   - [MÓDULO: ANIMACIONES, ESTADOS ACTIVOS Y BARRA FLOTANTE]
   - [MÓDULO: REQUERIR LOGIN Y PREVISUALIZACIÓN DE AVATAR]
   ============================================================================ */

(function () {
  'use strict';

  /* ==========================================================================
     [MÓDULO: CONFIGURACIÓN Y PALETA DE COLORES]
     Define la paleta de colores corporativos para SweetAlert2 y notificaciones.
     ========================================================================== */
  const COLORES = {
    success: '#0f766e',
    error: '#b91c1c',
    warning: '#b45309',
    info: '#0e7490',
    question: '#0f766e',
  };

  /* ==========================================================================
     [MÓDULO: FORMATO MONETARIO Y VALIDADORES]
     Funciones de conversión de texto a número y formateo en Pesos Colombianos (COP).
     ========================================================================== */
  
  // [FUNCIÓN: formatearCOP] Formatea un entero a moneda de Colombia ($ 150.000)
  function formatearCOP(valor) {
    const numero = Number(valor);
    if (!Number.isFinite(numero)) return '$0';
    return '$' + Math.round(numero).toLocaleString('es-CO');
  }

  // [FUNCIÓN: aNumero] Convierte valores string, nulos o vacíos en números float limpios
  function aNumero(valor) {
    if (typeof valor === 'number') return valor;
    if (valor === null || valor === undefined || valor === '') return 0;
    let texto = String(valor).trim().replace(/[^\d,.-]/g, '');
    if (texto.includes(',') && texto.includes('.')) {
      texto = texto.replace(/\./g, '').replace(',', '.');
    } else if (texto.includes(',')) {
      texto = texto.replace(',', '.');
    }
    const numero = parseFloat(texto);
    return Number.isFinite(numero) ? numero : 0;
  }

  // [FUNCIÓN: swalDisponible] Comprueba si la librería SweetAlert2 está cargada
  function swalDisponible() {
    return typeof window.Swal !== 'undefined';
  }

  /* ==========================================================================
     [MÓDULO: ALERTAS Y DIÁLOGOS SWEETALERT2]
     Genera modales emergentes de aviso, confirmación y notificaciones toast.
     ========================================================================== */
  
  // [FUNCIÓN: alerta] Abre modal informativo con SweetAlert2
  function alerta(opciones) {
    const config = Object.assign({
      icon: 'info',
      title: '',
      text: '',
      confirmButtonText: 'Entendido',
      confirmButtonColor: COLORES.info,
      customClass: { popup: 'wayra-swal' },
    }, opciones || {});

    if (!swalDisponible()) {
      window.alert(config.title + '\n' + (config.text || ''));
      return Promise.resolve({ isConfirmed: true });
    }
    return window.Swal.fire(config);
  }

  // [FUNCIÓN: confirmar] Abre diálogo modal con opciones (Sí / Cancelar)
  function confirmar(opciones) {
    const config = Object.assign({
      icon: 'question',
      title: '¿Confirmas esta acción?',
      text: '',
      showCancelButton: true,
      confirmButtonText: 'Sí, continuar',
      cancelButtonText: 'Cancelar',
      confirmButtonColor: COLORES.success,
      cancelButtonColor: '#64748b',
      reverseButtons: true,
      customClass: { popup: 'wayra-swal' },
    }, opciones || {});

    if (!swalDisponible()) {
      const texto = config.text || String(config.html || '').replace(/<[^>]*>/g, '');
      return Promise.resolve({ isConfirmed: window.confirm(config.title + '\n' + texto) });
    }
    return window.Swal.fire(config);
  }

  let toast = null;
  // [FUNCIÓN: notificar] Dispara una notificación flotante estilo Toast en la esquina superior
  function notificar(tipo, texto, titulo) {
    const icono = COLORES[tipo] ? tipo : 'info';
    if (!swalDisponible()) {
      console.log('[Wayra]', titulo || icono, texto);
      return;
    }
    if (!toast) {
      toast = window.Swal.mixin({
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 4600,
        timerProgressBar: true,
        customClass: { popup: 'wayra-toast' },
        didOpen: function (elemento) {
          elemento.addEventListener('mouseenter', window.Swal.stopTimer);
          elemento.addEventListener('mouseleave', window.Swal.resumeTimer);
        },
      });
    }
    toast.fire({ icon: icono, title: titulo || 'Posada Wayra', text: texto });
  }

  // [FUNCIÓN: procesarMensajes] Lee mensajes pasados desde el servidor Django y los notifica
  function procesarMensajes() {
    const avisos = document.querySelectorAll('[data-wayra-message]');
    if (avisos.length) {
      avisos.forEach(function (aviso, indice) {
        if (!swalDisponible()) return;
        const etiqueta = aviso.dataset.tipo || 'info';
        const tipo = etiqueta.includes('error') || etiqueta.includes('danger') ? 'error' :
          (etiqueta.includes('success') ? 'success' : (etiqueta.includes('warning') ? 'warning' : 'info'));
        window.setTimeout(function () { notificar(tipo, aviso.textContent.trim()); }, indice * 450);
        aviso.hidden = true;
      });
      return;
    }
    const nodo = document.getElementById('wayra-mensajes');
    if (!nodo) return;
    let mensajes = [];
    try {
      mensajes = JSON.parse(nodo.textContent || '[]');
    } catch (error) {
      console.warn('No se pudieron leer los mensajes del servidor.', error);
      return;
    }
    mensajes.forEach(function (mensaje, indice) {
      const tipo = mensaje.tipo === 'error' || mensaje.tipo === 'danger'
        ? 'error'
        : (mensaje.tipo === 'warning' ? 'warning' : (mensaje.tipo === 'success' ? 'success' : 'info'));
      window.setTimeout(function () {
        notificar(tipo, mensaje.texto);
      }, indice * 450);
    });
  }

  /* ==========================================================================
     [MÓDULO: ACCIONES GENERALES Y CONFIRMACIONES]
     Intercepta botones/formularios con atributo data-confirm antes de enviar.
     ========================================================================== */
  function ejecutarAccion(elemento) {
    if (elemento.tagName === 'A' && elemento.getAttribute('href')) {
      window.location.href = elemento.getAttribute('href');
      return;
    }
    const formulario = elemento.closest('form');
    if (formulario) {
      formulario.dataset.wayraConfirmado = '1';
      if (typeof formulario.requestSubmit === 'function') {
        formulario.requestSubmit(elemento.tagName === 'BUTTON' && elemento.type === 'submit' ? elemento : undefined);
      } else {
        formulario.submit();
      }
    }
  }

  function initConfirmaciones() {
    document.addEventListener('click', function (evento) {
      const elemento = evento.target.closest('[data-confirm]');
      if (!elemento || elemento.tagName === 'FORM') return;
      const formulario = elemento.closest('form');
      if (formulario && !formulario.reportValidity()) return;
      evento.preventDefault();
      evento.stopPropagation();
      confirmar({
        title: elemento.getAttribute('data-titulo') || '¿Confirmas esta acción?',
        text: elemento.getAttribute('data-confirm'),
        icon: elemento.getAttribute('data-icono') || 'question',
        confirmButtonText: elemento.getAttribute('data-accion') || 'Sí, continuar',
        confirmButtonColor: elemento.classList.contains('text-danger') ? COLORES.error : COLORES.success,
      }).then(function (resultado) {
        if (resultado.isConfirmed) ejecutarAccion(elemento);
      });
    });

    document.addEventListener('submit', function (evento) {
      const formulario = evento.target.closest('form');
      const elemento = formulario && (formulario.matches('[data-confirm]') ? formulario :
        (evento.submitter && evento.submitter.matches('[data-confirm]') ? evento.submitter : formulario.querySelector('button[data-confirm]')));
      if (!elemento) return;
      if (formulario.dataset.wayraConfirmado === '1') {
        if (formulario) delete formulario.dataset.wayraConfirmado;
        return;
      }
      if (evento.defaultPrevented) return;
      evento.preventDefault();
      confirmar({
        title: elemento.getAttribute('data-titulo') || '¿Confirmas esta acción?',
        text: elemento.getAttribute('data-confirm'),
        icon: elemento.getAttribute('data-icono') || 'question',
        confirmButtonText: elemento.getAttribute('data-accion') || 'Sí, continuar',
        confirmButtonColor: COLORES.success,
      }).then(function (resultado) {
        if (resultado.isConfirmed) ejecutarAccion(elemento);
      });
    });
  }

  /* ==========================================================================
     [MÓDULO: CONTROL DE CHECK-OUT Y SALDOS PENDIENTES]
     Bloquea el botón de Check-Out si el huésped registra deudas pendientes.
     ========================================================================== */
  function initCheckout() {
    document.addEventListener('click', function (evento) {
      const boton = evento.target.closest('[data-checkout]');
      if (!boton) return;
      const formulario = boton.closest('form');
      if (formulario && formulario.dataset.checkoutConfirmado === '1') return;
      evento.preventDefault();
      evento.stopPropagation();

      const saldo = aNumero(boton.getAttribute('data-saldo'));
      const habitacion = boton.getAttribute('data-habitacion') || '';
      if (saldo > 0) {
        boton.setAttribute('aria-disabled', 'true');
        alerta({
          icon: 'error',
          title: '¡Acción bloqueada!',
          text: 'El cliente registra un saldo pendiente de ' + formatearCOP(saldo) +
            '. Debe estar totalmente saldado.' + (habitacion ? ' Habitación ' + habitacion + '.' : ''),
          confirmButtonText: 'Entendido',
          confirmButtonColor: COLORES.error,
        });
        return;
      }

      confirmar({
        title: 'Registrar Check-Out',
        text: 'El saldo está totalmente cubierto. ¿Deseas finalizar la estadía y enviar la habitación a limpieza?',
        icon: 'question',
        confirmButtonText: 'Sí, registrar salida',
      }).then(function (resultado) {
        if (resultado.isConfirmed) {
          const formulario = boton.closest('form');
          if (formulario) formulario.dataset.checkoutConfirmado = '1';
          ejecutarAccion(boton);
        }
      });
    });
    document.addEventListener('submit', function (evento) {
      const formulario = evento.target;
      const boton = formulario.querySelector('button[data-checkout]');
      if (!boton || evento.defaultPrevented) return;
      if (formulario.dataset.checkoutConfirmado === '1') {
        delete formulario.dataset.checkoutConfirmado;
        return;
      }
      evento.preventDefault();
      boton.click();
    });
  }

  /* ==========================================================================
     [MÓDULO: POLÍTICA DE NO-SHOW]
     Pide confirmación expresa sobre cancelación sin reembolso por inasistencia.
     ========================================================================== */
  function initPoliticaNoShow() {
    document.addEventListener('submit', function (evento) {
      const formulario = evento.target.closest('form[data-politica-no-show]');
      if (!formulario || evento.defaultPrevented || formulario.dataset.noShowConfirmado === '1') return;

      evento.preventDefault();
      confirmar({
        icon: 'warning',
        title: 'Política de No-Show',
        html: 'Para garantizar la reserva debes abonar mínimo <strong>1 noche</strong>. ' +
          'Debes presentarte el primer día pactado; si no realizas el check-in ese día, ' +
          'recepción podrá cancelar la reserva <strong>sin derecho a reembolso</strong>. ' +
          'Esta solicitud registra el abono declarado; no realiza cargos bancarios.',
        confirmButtonText: 'Acepto y solicitar reserva',
        cancelButtonText: 'Revisar reserva',
      }).then(function (resultado) {
        if (resultado.isConfirmed) {
          formulario.dataset.noShowConfirmado = '1';
          HTMLFormElement.prototype.submit.call(formulario);
        }
      });
    });
  }

  /* ==========================================================================
     [MÓDULO: REQUERIR LOGIN Y PREVISUALIZACIÓN DE AVATAR]
     Maneja solicitud de autenticación y carga de fotos de perfil.
     ========================================================================== */
  function initAccesoReserva() {
    document.addEventListener('click', function (evento) {
      const boton = evento.target.closest('[data-requiere-login]');
      if (!boton) return;
      evento.preventDefault();
      evento.stopPropagation();

      const next = boton.getAttribute('data-next') || window.location.pathname;
      const loginUrl = boton.getAttribute('data-login-url');
      const registroUrl = boton.getAttribute('data-registro-url');

      window.Swal.fire({
        icon: 'info',
        title: 'Inicia sesión para confirmar',
        html: 'Para confirmar tu reserva necesitas <strong>iniciar sesión</strong> o <strong>crear una cuenta</strong>. ' +
          'Tus fechas y la habitación seleccionada se conservarán.',
        showDenyButton: true,
        showCancelButton: true,
        confirmButtonText: 'Iniciar sesión',
        denyButtonText: 'Crear cuenta',
        cancelButtonText: 'Seguir explorando',
        confirmButtonColor: COLORES.info,
        denyButtonColor: COLORES.success,
        cancelButtonColor: '#64748b',
        customClass: { popup: 'wayra-swal' },
      }).then(function (resultado) {
        if (resultado.isConfirmed && loginUrl) {
          window.location.href = loginUrl + '?next=' + encodeURIComponent(next);
        } else if (resultado.isDenied && registroUrl) {
          window.location.href = registroUrl + '?next=' + encodeURIComponent(next);
        }
      });
    });
  }

  function initAvatarPreview() {
    document.querySelectorAll('[data-avatar-input]').forEach(function (input) {
      const contenedor = input.closest('form') || document;
      const preview = contenedor.querySelector('[data-avatar-preview]') || input.closest('.panel-body')?.querySelector('[data-avatar-preview]');
      if (!preview) return;
      input.addEventListener('change', function () {
        const archivo = input.files && input.files[0];
        if (!archivo) return;
        if (!archivo.type.startsWith('image/')) {
          input.value = '';
          notificar('error', 'Selecciona un archivo de imagen válido.', 'Formato no admitido');
          return;
        }
        if (archivo.size > 4 * 1024 * 1024) {
          input.value = '';
          notificar('error', 'La imagen no puede superar los 4 MB.', 'Archivo demasiado grande');
          return;
        }
        const lector = new FileReader();
        lector.onload = function (evento) {
          if (preview.tagName === 'IMG') {
            preview.src = evento.target.result;
            preview.classList.remove('d-none');
          } else {
            preview.style.backgroundImage = 'url(' + evento.target.result + ')';
            preview.textContent = '';
          }
        };
        lector.readAsDataURL(archivo);
      });
    });
  }

  function initReservasStaff() {
    document.querySelectorAll('form[data-reserva-ocupacion]').forEach(function (formulario) {
      const habitacion = formulario.querySelector('[name="habitacion"]');
      const adultos = formulario.querySelector('[name="adultos"]');
      const ninos = formulario.querySelector('[name="ninos"]');
      const ayuda = formulario.querySelector('#textoCapacidad');
      const entrada = formulario.querySelector('[name="fecha_entrada"]');
      const salida = formulario.querySelector('[name="fecha_salida"]');
      if (!habitacion || !adultos || !ninos) return;
      function validar() {
        const opcion = habitacion.options[habitacion.selectedIndex];
        const capacidad = Number.parseInt(opcion?.dataset.capacidad, 10);
        const maxAdultos = Number.parseInt(opcion?.dataset.maxAdultos, 10);
        const maxNinos = Number.parseInt(opcion?.dataset.maxNinos, 10);
        adultos.setCustomValidity('');
        ninos.setCustomValidity('');
        if (Number.isFinite(maxAdultos)) adultos.max = maxAdultos;
        else adultos.removeAttribute('max');
        if (Number.isFinite(maxNinos)) ninos.max = maxNinos;
        else ninos.removeAttribute('max');
        if (capacidad > 0 && Number(adultos.value) + Number(ninos.value) > capacidad) {
          ninos.setCustomValidity('La suma de adultos y niños no puede superar ' + capacidad + ' huéspedes.');
        }
        if (ayuda) ayuda.textContent = capacidad > 0 ? 'Capacidad total: ' + capacidad + ' huéspedes. ' +
          (Number.isFinite(maxAdultos) ? 'Máx. ' + maxAdultos + ' adultos. ' : '') +
          (Number.isFinite(maxNinos) ? 'Máx. ' + maxNinos + ' niños.' : '') : 'Selecciona una habitación para consultar su capacidad.';
        if (salida && entrada) salida.setCustomValidity(entrada.value && salida.value && salida.value <= entrada.value ? 'La salida debe ser posterior a la entrada.' : '');
      }
      [habitacion, adultos, ninos, entrada, salida].filter(Boolean).forEach(function (campo) {
        campo.addEventListener('input', validar);
        campo.addEventListener('change', validar);
      });
      formulario.addEventListener('submit', function (evento) {
        validar();
        if (!formulario.reportValidity()) evento.preventDefault();
      });
      validar();
    });
  }

  function initNavegacion() {
    document.querySelector('[data-sidebar-toggle]')?.addEventListener('click', function () {
      const sidebar = document.querySelector('.app-sidebar');
      if (sidebar) this.setAttribute('aria-expanded', String(sidebar.classList.toggle('show')));
    });
    document.querySelector('[data-staff-search]')?.addEventListener('input', function () {
      const termino = this.value.trim().toLocaleLowerCase('es');
      document.querySelectorAll('.app-main table tbody tr').forEach(function (fila) {
        fila.hidden = Boolean(termino) && !fila.textContent.toLocaleLowerCase('es').includes(termino);
      });
    });
    const modal = document.getElementById('roomGalleryModal');
    modal?.addEventListener('show.bs.modal', function (evento) {
      const carousel = modal.querySelector('.carousel');
      if (carousel && window.bootstrap) {
        bootstrap.Carousel.getOrCreateInstance(carousel, { interval: false }).to(Number(evento.relatedTarget?.dataset.roomSlide) || 0);
      }
    });
  }

  function initTooltips() {
    if (!window.bootstrap || !bootstrap.Tooltip) return;
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (elemento) {
      bootstrap.Tooltip.getOrCreateInstance(elemento);
    });
  }

  // Inicialización de submódulos principales al cargar el DOM
  document.addEventListener('DOMContentLoaded', function () {
    procesarMensajes();
    initConfirmaciones();
    initCheckout();
    initPoliticaNoShow();
    initAccesoReserva();
    initAvatarPreview();
    initReservasStaff();
    initNavegacion();
    initTooltips();
  });

  // Exportar funciones globalmente en window.WayraUI
  window.WayraUI = {
    alerta: alerta,
    confirmar: confirmar,
    notificar: notificar,
    formatearCOP: formatearCOP,
    aNumero: aNumero,
  };
})();





/* Selector de huéspedes: límites enviados por el catálogo, sin capacidad inventada. */
function sincronizarHuespedesWayra(selector) {
  let total = 0;
  ['adultos', 'ninos'].forEach(function (tipo) {
    const minimo = tipo === 'adultos' ? 1 : 0;
    const limite = Number.parseInt(selector.dataset[tipo === 'adultos' ? 'maxAdultos' : 'maxNinos'], 10);
    const maximo = Number.isFinite(limite) ? Math.max(minimo, limite) : null;
    const input = selector.querySelector('[data-guest-input="' + tipo + '"]');
    const output = selector.querySelector('[data-guest-count="' + tipo + '"]');
    if (!input || !output) return;
    let valor = Number.parseInt(input.value, 10);
    valor = Math.max(minimo, Number.isFinite(valor) ? valor : minimo);
    if (maximo !== null) valor = Math.min(valor, maximo);
    input.value = valor;
    output.textContent = valor;
    total += valor;
    selector.querySelectorAll('[data-guest-step="' + tipo + '"]').forEach(function (boton) {
      boton.disabled = Number(boton.dataset.step) < 0 ? valor <= minimo : maximo !== null && valor >= maximo;
    });
  });
  const inputTotal = selector.querySelector('[data-guest-input="total"]');
  if (inputTotal) inputTotal.value = total;
  const adultos = Number(selector.querySelector('[data-guest-input="adultos"]').value);
  const ninos = Number(selector.querySelector('[data-guest-input="ninos"]').value);
  const resumen = selector.querySelector('[data-guest-summary]');
  if (resumen) resumen.textContent = adultos + ' adulto' + (adultos === 1 ? '' : 's') +
    (ninos ? ' · ' + ninos + ' niño' + (ninos === 1 ? '' : 's') : '') + ' · 1 habitación';
}

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-guest-selector]').forEach(sincronizarHuespedesWayra);
});

document.addEventListener('click', function (evento) {
  const boton = evento.target.closest('[data-guest-step]');
  if (!boton) return;
  evento.preventDefault();
  evento.stopPropagation();
  const selector = boton.closest('[data-guest-selector]');
  const input = selector && selector.querySelector('[data-guest-input="' + boton.dataset.guestStep + '"]');
  if (!input || boton.disabled) return;
  input.value = Number(input.value) + Number(boton.dataset.step);
  sincronizarHuespedesWayra(selector);
  if (typeof window.actualizarCalendariosWayra === 'function') window.actualizarCalendariosWayra();
}, true);






/* Calendario de dos meses: fechas locales y precios únicamente del servidor. */
document.addEventListener('DOMContentLoaded', function () {
  const campo = document.querySelector('[data-datepicker-field]');
  if (!campo) return;
  const formulario = campo.closest('form');
  const inputInicio = campo.querySelector('[name="fecha_inicio"]');
  const inputFin = campo.querySelector('[name="fecha_fin"]');
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  let fechaCheckIn = inputInicio.value || null;
  let fechaCheckOut = inputFin.value || null;
  let mesActual = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
  const fechaLocal = function (iso) {
    const partes = iso.split('-').map(Number);
    return new Date(partes[0], partes[1] - 1, partes[2]);
  };
  if (fechaCheckIn && fechaLocal(fechaCheckIn) >= hoy) {
    const inicio = fechaLocal(fechaCheckIn);
    mesActual = new Date(inicio.getFullYear(), inicio.getMonth(), 1);
  } else {
    fechaCheckIn = null;
    fechaCheckOut = null;
  }
  if (fechaCheckOut && (!fechaCheckIn || fechaCheckOut <= fechaCheckIn)) fechaCheckOut = null;

  let tarifas = null;
  const datos = document.getElementById('wayra-tarifas-calendario');
  if (datos) {
    try {
      tarifas = JSON.parse(datos.textContent);
      if (typeof tarifas === 'string') tarifas = JSON.parse(tarifas);
    } catch (error) {
      console.warn('Tarifas de calendario no válidas; se muestran solo fechas.', error);
    }
  }
  function obtenerPrecioFecha(iso) {
    if (!tarifas || !tarifas.precios_por_adultos) return '';
    const adultos = formulario.querySelector('[name="adultos"]')?.value;
    const ninos = formulario.querySelector('[name="ninos"]')?.value;
    const porAdultos = tarifas.precios_por_adultos[adultos];
    const precio = porAdultos && typeof porAdultos === 'object' ? porAdultos[ninos] : porAdultos;
    const valor = precio && typeof precio === 'object' ? precio[iso] : precio;
    if (valor === undefined || valor === null || valor === '' || !Number.isFinite(Number(valor)) || Number(valor) <= 0) return '';
    return window.WayraUI.formatearCOP(valor);
  }
  function actualizarResumenTexto() {
    const resumen = campo.querySelector('[data-date-summary]');
    const textoFecha = function (iso) {
      return fechaLocal(iso).toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short' });
    };
    if (resumen) resumen.textContent = fechaCheckIn ? textoFecha(fechaCheckIn) + ' ━ ' +
      (fechaCheckOut ? textoFecha(fechaCheckOut) : 'Selecciona salida') : 'Entrada ━ Salida';
    inputInicio.value = fechaCheckIn || '';
    inputFin.value = fechaCheckOut || '';
  }
  function cerrarDesplegableFechas() {
    actualizarResumenTexto();
    const trigger = campo.querySelector('[data-bs-toggle="dropdown"]');
    if (trigger && window.bootstrap) bootstrap.Dropdown.getOrCreateInstance(trigger).hide();
  }
  function renderizarMes(fechaMes, id) {
    const contenedor = campo.querySelector('#' + id);
    if (!contenedor) return;
    const anio = fechaMes.getFullYear();
    const mes = fechaMes.getMonth();
    const nombre = fechaMes.toLocaleDateString('es-CO', { month: 'long', year: 'numeric' });
    const inicioSemana = (new Date(anio, mes, 1).getDay() + 6) % 7;
    const ultimo = new Date(anio, mes + 1, 0).getDate();
    let html = '<div class="pw-month-title text-capitalize">' + nombre + '</div>' +
      '<div class="pw-week-days"><span>Lun</span><span>Mar</span><span>Mié</span><span>Jue</span><span>Vie</span><span>Sáb</span><span>Dom</span></div><div class="pw-days-grid">';
    for (let i = 0; i < inicioSemana; i++) html += '<span aria-hidden="true"></span>';
    for (let dia = 1; dia <= ultimo; dia++) {
      const fecha = new Date(anio, mes, dia);
      const iso = anio + '-' + String(mes + 1).padStart(2, '0') + '-' + String(dia).padStart(2, '0');
      const pasado = fecha < hoy;
      const seleccionado = iso === fechaCheckIn || iso === fechaCheckOut;
      let clases = 'pw-day-cell';
      if (pasado) clases += ' disabled';
      if (iso === fechaCheckIn) clases += ' selected-start';
      if (iso === fechaCheckOut) clases += ' selected-end';
      if (fechaCheckIn && fechaCheckOut && iso > fechaCheckIn && iso < fechaCheckOut) clases += ' in-range';
      const precio = pasado ? '' : obtenerPrecioFecha(iso);
      html += '<button type="button" class="' + clases + '" data-date="' + iso + '" aria-label="' +
        fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'long', year: 'numeric' }) +
        '" aria-pressed="' + seleccionado + '"' + (pasado ? ' disabled' : '') + '><span class="pw-day-num">' + dia +
        '</span>' + (precio ? '<span class="pw-day-price">' + precio + '</span>' : '') + '</button>';
    }
    contenedor.innerHTML = html + '</div>';
  }
  window.actualizarCalendariosWayra = function () {
    const siguiente = new Date(mesActual.getFullYear(), mesActual.getMonth() + 1, 1);
    renderizarMes(mesActual, 'monthBlock1');
    renderizarMes(siguiente, 'monthBlock2');
    const etiqueta = campo.querySelector('#pwCalendarRangeLabel');
    if (etiqueta) etiqueta.textContent = mesActual.toLocaleDateString('es-CO', { month: 'long', year: 'numeric' }) +
      ' — ' + siguiente.toLocaleDateString('es-CO', { month: 'long', year: 'numeric' });
    const anterior = campo.querySelector('#pwPrevMonth');
    if (anterior) anterior.disabled = mesActual <= new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    const trigger = campo.querySelector('[data-bs-toggle="dropdown"]');
    if (trigger && window.bootstrap) bootstrap.Dropdown.getInstance(trigger)?.update();
  };
  campo.addEventListener('click', function (evento) {
    const boton = evento.target.closest('button[data-date]');
    if (!boton || boton.disabled) return;
    const iso = boton.dataset.date;
    if (iso === fechaCheckIn) {
      fechaCheckIn = null;
      fechaCheckOut = null;
    } else if (iso === fechaCheckOut) {
      fechaCheckOut = null;
    } else if (!fechaCheckIn || fechaCheckOut) {
      fechaCheckIn = iso;
      fechaCheckOut = null;
    } else if (iso > fechaCheckIn) {
      fechaCheckOut = iso;
    } else {
      fechaCheckIn = iso;
      fechaCheckOut = null;
    }
    actualizarResumenTexto();
    window.actualizarCalendariosWayra();
    if (fechaCheckIn && fechaCheckOut) cerrarDesplegableFechas();
  });
  campo.querySelector('#pwPrevMonth')?.addEventListener('click', function () {
    mesActual = new Date(mesActual.getFullYear(), mesActual.getMonth() - 1, 1);
    window.actualizarCalendariosWayra();
  });
  campo.querySelector('#pwNextMonth')?.addEventListener('click', function () {
    mesActual = new Date(mesActual.getFullYear(), mesActual.getMonth() + 1, 1);
    window.actualizarCalendariosWayra();
  });
  formulario.addEventListener('submit', function (evento) {
    if (fechaCheckIn && fechaCheckOut && fechaCheckOut > fechaCheckIn) return;
    evento.preventDefault();
    window.WayraUI.notificar('warning', 'Selecciona una fecha de entrada y una fecha de salida posterior.');
    const trigger = campo.querySelector('[data-bs-toggle="dropdown"]');
    if (trigger && window.bootstrap) bootstrap.Dropdown.getOrCreateInstance(trigger).show();
  });
  actualizarResumenTexto();
  window.actualizarCalendariosWayra();
});


document.addEventListener('DOMContentLoaded', function () {
  const buscador = document.querySelector('.pw-portal-search-card');
  if (!buscador) return;
  const ancla = document.createElement('div');
  buscador.before(ancla);
  ancla.append(buscador);
  function reservarEspacio() {
    ancla.style.minHeight = buscador.offsetHeight + 28 + 'px';
  }
  reservarEspacio();
  new ResizeObserver(reservarEspacio).observe(buscador);
  new IntersectionObserver(function (entradas) {
    const entrada = entradas[0];
    buscador.classList.toggle('is-sticky', !entrada.isIntersecting && entrada.boundingClientRect.top < 0);
  }).observe(ancla);
});



/* ============================================================================
   [MÓDULO: SELECTOR DE HUÉSPEDES - BOTÓN APLICAR]
   ----------------------------------------------------------------------------
   - cierra el boton de  "Aplicar". al hacer click
   ============================================================================ */
document.addEventListener('click', function (e) {
  const applyBtn = e.target.closest('[data-guest-apply]');
  if (!applyBtn) return;

  e.preventDefault();
  const selector = applyBtn.closest('[data-guest-selector]');
  if (!selector) return;

  const trigger = selector.querySelector('[data-bs-toggle="dropdown"]');
  if (trigger) {
    // 1. Intenta cerrar usando la API nativa de Bootstrap
    if (window.bootstrap && bootstrap.Dropdown) {
      const dropdown = bootstrap.Dropdown.getOrCreateInstance(trigger);
      dropdown.hide();
    } else {
      // 2. Fallback: simula el clic en el botón disparador para alternar/cerrar el desplegable
      trigger.click();
    }
  }
});