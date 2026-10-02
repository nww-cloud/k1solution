// 대시보드 캘린더 + 휴가 신청 다이얼로그 상호작용.
// 서버 렌더링을 기본으로 하고, 이 스크립트는 다이얼로그 열기/닫기와
// 신청 미리보기(실시간 일수·잔여 계산)만 보강한다. JS가 꺼져 있어도
// /leave/request 페이지로 직접 이동해 신청할 수 있다.
(function () {
    "use strict";

    function onReady(fn) {
        if (document.readyState !== "loading") fn();
        else document.addEventListener("DOMContentLoaded", fn);
    }

    onReady(function () {
        var dialog = document.getElementById("requestDialog");

        document.querySelectorAll("[data-open-request]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (dialog && typeof dialog.showModal === "function") {
                    dialog.showModal();
                    updatePreview();
                } else {
                    window.location.href = "/leave/request";
                }
            });
        });

        document.querySelectorAll("[data-close-request]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (dialog) dialog.close();
            });
        });

        // 캘린더 날짜 더블클릭 -> 해당 날짜로 신청 다이얼로그 열기
        document.querySelectorAll(".cal-day").forEach(function (cell) {
            cell.addEventListener("dblclick", function (e) {
                e.preventDefault();
                var d = cell.getAttribute("data-date");
                var startEl = document.getElementById("start_date");
                var endEl = document.getElementById("end_date");
                if (startEl) startEl.value = d;
                if (endEl) endEl.value = d;
                if (dialog && typeof dialog.showModal === "function") {
                    dialog.showModal();
                    updatePreview();
                } else {
                    window.location.href = "/leave/request?date=" + d;
                }
            });
        });

        var unitSelect = document.getElementById("unit_select");
        var unitHidden = document.getElementById("unit_hidden");
        var unitLabelHidden = document.getElementById("unit_label_hidden");
        var startEl = document.getElementById("start_date");
        var endEl = document.getElementById("end_date");

        function syncUnitHiddenFields() {
            if (!unitSelect) return;
            var opt = unitSelect.options[unitSelect.selectedIndex];
            var unitValue = parseFloat(opt.getAttribute("data-unit"));
            unitHidden.value = unitValue;
            unitLabelHidden.value = opt.getAttribute("data-label");

            // 반차/반반차 등 부분 단위는 하루만 신청 가능 -> 종료일을 시작일에 맞추고 잠근다.
            // disabled로 잠그면 폼 제출 시 값이 아예 전송되지 않으므로 readOnly를 쓴다.
            if (endEl) {
                if (unitValue !== 1.0) {
                    endEl.value = startEl.value;
                    endEl.readOnly = true;
                    endEl.style.background = "#f3f4f6";
                } else {
                    endEl.readOnly = false;
                    endEl.style.background = "";
                }
            }
        }

        async function updatePreview() {
            syncUnitHiddenFields();

            var previewTotal = document.getElementById("previewTotalDays");
            var previewRemaining = document.getElementById("previewRemainingAfter");
            var errorsEl = document.getElementById("previewErrors");
            var submitBtn = document.getElementById("submitRequestBtn");
            if (!startEl || !endEl || !startEl.value || !endEl.value) return;

            var kindEl = document.getElementById("kind");

            try {
                var resp = await fetch("/leave/request/preview", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        start_date: startEl.value,
                        end_date: endEl.value,
                        kind: kindEl ? kindEl.value : "연차",
                        unit: parseFloat(unitHidden.value),
                    }),
                });
                var data = await resp.json();

                if (previewTotal) previewTotal.textContent = data.total_days + "일";
                if (previewRemaining) {
                    previewRemaining.textContent = data.remaining_after + "일";
                    previewRemaining.classList.toggle("bad", data.remaining_after < 0);
                }
                if (errorsEl) {
                    errorsEl.innerHTML = "";
                    (data.errors || []).forEach(function (err) {
                        var li = document.createElement("li");
                        li.textContent = err;
                        errorsEl.appendChild(li);
                    });
                }
                if (submitBtn) submitBtn.disabled = !!(data.errors && data.errors.length);
            } catch (e) {
                // 네트워크 오류 시 미리보기만 비활성화하고, 서버 측 검증은 그대로 제출 시 동작한다.
            }
        }

        [startEl, endEl, document.getElementById("kind"), unitSelect].forEach(function (el) {
            if (!el) return;
            el.addEventListener("change", updatePreview);
        });

        if (dialog) {
            dialog.addEventListener("close", function () {
                var errorsEl = document.getElementById("previewErrors");
                if (errorsEl) errorsEl.innerHTML = "";
            });
        }

        // 대시보드 외 신청 페이지(단독)에서도 동일하게 미리보기 보강
        if (!dialog && startEl && endEl) {
            updatePreview();
        }
    });
})();
