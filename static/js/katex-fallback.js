/* Respaldo local de KaTeX.
 *
 * La página carga KaTeX desde CDN. En un centro sin internet ese recurso falla
 * y la documentación de ecuaciones quedaría sin renderizar, que es justo donde
 * más se necesita. Este script detecta el fallo y carga la copia vendorizada de
 * static/vendor/katex/ — el mismo patrón que ya usa static/vendor/three/.
 */
(function () {
    'use strict';

    var BASE = '/static/vendor/katex/';

    function injectCss() {
        if (document.querySelector('link[data-katex-local]')) return;
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = BASE + 'katex.min.css';
        link.setAttribute('data-katex-local', '1');
        document.head.appendChild(link);
    }

    function injectJs(done) {
        if (document.querySelector('script[data-katex-local]')) { done(); return; }
        var script = document.createElement('script');
        script.src = BASE + 'katex.min.js';
        script.setAttribute('data-katex-local', '1');
        script.onload = done;
        script.onerror = function () {
            console.warn('[katex] No se pudo cargar KaTeX ni desde CDN ni localmente. ' +
                         'Las ecuaciones se mostrarán como texto TeX.');
            done();
        };
        document.head.appendChild(script);
    }

    function ensure() {
        if (window.__katexCssFailed) injectCss();

        if (typeof window.katex === 'undefined') {
            injectJs(function () {
                injectCss();
                // Re-renderiza lo que ya esté visible en el drawer.
                if (typeof window.renderKatexIn === 'function') {
                    window.renderKatexIn(document.getElementById('help_body'));
                }
            });
        }
    }

    // El <script> del CDN es defer; damos una vuelta de event loop antes de decidir.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { setTimeout(ensure, 0); });
    } else {
        setTimeout(ensure, 0);
    }
})();
