// 대시보드 캘린더 + 휴가 신청 다이얼로그 상호작용.
//
// 날짜 선택 방식(목업 02/03 문서 기준, 마우스 드래그만 제외):
// - 상태는 하나(activeField: 'start'|'end')이고 진입구가 셋이다.
//   1) "연속 휴가로 선택" 버튼  2) 종료일 입력칸 클릭/포커스  3) 미니 달력 클릭
// - 시작일 선택 중(기본): 달력 클릭 -> 그 하루로 이동(항상 단일 선택으로 초기화)
// - 종료일 선택 중: 달력 클릭 -> 기간 확정, 역행 선택(시작일보다 이른 날짜) 허용,
//   확정 후 자동으로 시작일 선택 중으로 복귀
// - 반차 등 부분 단위는 하루만 가능 -> 범위 선택 버튼 비활성, 달력 클릭도 항상 단일 선택
// - 입력칸에 직접 타이핑하면 활성 칸은 시작일로 복귀
//
// 미니 달력은 월이 바뀔 때마다 /leave/calendar-data 를 호출해 본인 일정과
// 같은 부서 동료 부재를 날짜 칸에 함께 표시한다.
(function () {
    "use strict";

    function onReady(fn) {
        if (document.readyState !== "loading") fn();
        else document.addEventListener("DOMContentLoaded", fn);
    }

    function pad(n) { return n < 10 ? "0" + n : "" + n; }
    function formatDate(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
    function parseDate(s) {
        var parts = s.split("-").map(Number);
        return new Date(parts[0], parts[1] - 1, parts[2]);
    }
    function addDays(d, n) { var r = new Date(d); r.setDate(r.getDate() + n); return r; }
    function isWeekend(d) { var w = d.getDay(); return w === 0 || w === 6; }
    function sameDate(a, b) { return !!a && !!b && formatDate(a) === formatDate(b); }
    function escapeHtml(s) {
        var div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    }

    onReady(function () {
        var dialog = document.getElementById("requestDialog");
        var startEl = document.getElementById("start_date");
        var endEl = document.getElementById("end_date");
        var kindEl = document.getElementById("kind");
        var unitButtons = Array.prototype.slice.call(document.querySelectorAll(".dash-unit-btn"));
        var unitHidden = document.getElementById("unit_hidden");
        var unitLabelHidden = document.getElementById("unit_label_hidden");
        var startBadge = document.getElementById("startBadge");
        var endBadge = document.getElementById("endBadge");
        var rangeModeBtn = document.getElementById("rangeModeBtn");
        var absenceBanner = document.getElementById("absenceBanner");
        var miniMonthLabel = document.getElementById("miniMonthLabel");
        var miniCalBody = document.getElementById("miniCalBody");
        var miniPrev = document.getElementById("miniPrev");
        var miniNext = document.getElementById("miniNext");
        var miniToday = document.getElementById("miniToday");

        if (!startEl || !endEl) return; // 신청 폼 자체가 없는 페이지

        var hasMiniCalendar = !!miniCalBody;
        var monthEventCache = {}; // "YYYY-M" -> {days: {...}}

        var picker = {
            viewYear: new Date().getFullYear(),
            viewMonth: new Date().getMonth(),
            activeField: "start",
        };

        function currentUnit() {
            var active = unitButtons.filter(function (b) { return b.classList.contains("dash-active"); })[0];
            return active ? parseFloat(active.getAttribute("data-unit")) : 1.0;
        }

        function getStartEnd() {
            return {
                start: startEl.value ? parseDate(startEl.value) : null,
                end: endEl.value ? parseDate(endEl.value) : null,
            };
        }

        function setStartEnd(s, e) {
            startEl.value = s ? formatDate(s) : "";
            endEl.value = e ? formatDate(e) : "";
        }

        function updateBadgeAndButton() {
            var partial = currentUnit() !== 1.0;
            if (rangeModeBtn) {
                if (partial) {
                    rangeModeBtn.disabled = true;
                    rangeModeBtn.textContent = "하루 단위라 기간 선택이 없어요";
                    rangeModeBtn.classList.remove("dash-active");
                } else if (picker.activeField === "end") {
                    rangeModeBtn.disabled = false;
                    rangeModeBtn.textContent = "종료일 고르는 중 · 눌러서 취소";
                    rangeModeBtn.classList.add("dash-active");
                } else {
                    rangeModeBtn.disabled = false;
                    rangeModeBtn.textContent = "연속 휴가로 선택";
                    rangeModeBtn.classList.remove("dash-active");
                }
            }
            if (startBadge) startBadge.classList.toggle("dash-hidden", picker.activeField !== "start");
            if (endBadge) endBadge.classList.toggle("dash-hidden", picker.activeField !== "end");
        }

        function monthKey(y, m) { return y + "-" + m; }

        function fetchMonthEvents(y, m) {
            var key = monthKey(y, m);
            if (monthEventCache[key]) return Promise.resolve(monthEventCache[key]);
            return fetch("/leave/calendar-data?year=" + y + "&month=" + (m + 1))
                .then(function (r) { return r.ok ? r.json() : { days: {} }; })
                .then(function (data) {
                    monthEventCache[key] = data.days || {};
                    return monthEventCache[key];
                })
                .catch(function () { return {}; });
        }

        function renderMiniCalendar() {
            if (!hasMiniCalendar) return;
            var y = picker.viewYear, m = picker.viewMonth;
            if (miniMonthLabel) miniMonthLabel.textContent = y + "년 " + (m + 1) + "월";

            fetchMonthEvents(y, m).then(function (events) {
                var firstOfMonth = new Date(y, m, 1);
                var gridStart = addDays(firstOfMonth, -firstOfMonth.getDay());
                var today = new Date();
                var cur = getStartEnd();

                var html = "";
                for (var week = 0; week < 6; week++) {
                    html += "<tr>";
                    for (var dow = 0; dow < 7; dow++) {
                        var d = addDays(gridStart, week * 7 + dow);
                        var dateStr = formatDate(d);
                        var classes = ["dash-mini-day"];
                        if (d.getMonth() !== m) classes.push("dash-other-month");
                        if (isWeekend(d)) classes.push("dash-weekend");
                        if (sameDate(d, today)) classes.push("dash-today");
                        if (cur.start && cur.end && d >= cur.start && d <= cur.end) classes.push("dash-in-range");
                        if (sameDate(d, cur.start)) classes.push("dash-range-start");
                        if (sameDate(d, cur.end)) classes.push("dash-range-end");

                        var inner = '<span class="dash-mini-day-num">' + d.getDate() + "</span>";
                        var dayEvents = events[dateStr];
                        if (dayEvents) {
                            (dayEvents.own || []).forEach(function (ev) {
                                inner += '<span class="dash-mini-event dash-mine">내 휴가 · ' + escapeHtml(ev.unit_label) + "</span>";
                            });
                            (dayEvents.colleagues || []).forEach(function (name) {
                                inner += '<span class="dash-mini-event dash-team">' + escapeHtml(name) + "</span>";
                            });
                        }

                        html += '<td class="' + classes.join(" ") + '" data-date="' + dateStr + '">' + inner + "</td>";
                    }
                    html += "</tr>";
                }
                miniCalBody.innerHTML = html;
            });
        }

        function onMiniDayClick(dateStr) {
            var clicked = parseDate(dateStr);

            if (currentUnit() !== 1.0 || picker.activeField === "start") {
                setStartEnd(clicked, clicked);
                onDatesChanged();
                return;
            }

            var cur = getStartEnd();
            var s = cur.start || clicked;
            if (clicked < s) {
                setStartEnd(clicked, s);
            } else {
                setStartEnd(s, clicked);
            }
            picker.activeField = "start";
            onDatesChanged();
        }

        function onDatesChanged() {
            updateBadgeAndButton();
            updatePreview();
        }

        function goToMonth(y, m) {
            if (m < 0) { m = 11; y -= 1; }
            if (m > 11) { m = 0; y += 1; }
            picker.viewYear = y;
            picker.viewMonth = m;
            renderMiniCalendar();
        }

        if (hasMiniCalendar) {
            miniCalBody.addEventListener("click", function (e) {
                var td = e.target.closest(".dash-mini-day");
                if (!td) return;
                onMiniDayClick(td.getAttribute("data-date"));
            });
            if (miniPrev) miniPrev.addEventListener("click", function () { goToMonth(picker.viewYear, picker.viewMonth - 1); });
            if (miniNext) miniNext.addEventListener("click", function () { goToMonth(picker.viewYear, picker.viewMonth + 1); });
            if (miniToday) {
                miniToday.addEventListener("click", function () {
                    var t = new Date();
                    goToMonth(t.getFullYear(), t.getMonth());
                });
            }
            if (rangeModeBtn) {
                rangeModeBtn.addEventListener("click", function () {
                    if (currentUnit() !== 1.0) return;
                    picker.activeField = picker.activeField === "end" ? "start" : "end";
                    updateBadgeAndButton();
                    renderMiniCalendar();
                });
            }
            endEl.addEventListener("focus", function () {
                if (currentUnit() !== 1.0) return;
                picker.activeField = "end";
                updateBadgeAndButton();
                renderMiniCalendar();
            });
        }

        // 입력칸에 직접 날짜를 넣으면 활성 칸은 시작일로 복귀
        [startEl, endEl].forEach(function (el) {
            el.addEventListener("change", function () {
                picker.activeField = "start";
                onDatesChanged();
            });
        });

        // ---- 사용 단위 버튼 ----
        unitButtons.forEach(function (btn) {
            btn.addEventListener("click", function () {
                unitButtons.forEach(function (b) { b.classList.remove("dash-active"); });
                btn.classList.add("dash-active");
                updatePreview();
            });
        });

        // ---- 다이얼로그 열기/닫기 ----

        function openDialogAt(dateStr) {
            if (dateStr) {
                var d = parseDate(dateStr);
                picker.viewYear = d.getFullYear();
                picker.viewMonth = d.getMonth();
                setStartEnd(d, d);
            }
            picker.activeField = "start";
            if (dialog && typeof dialog.showModal === "function") dialog.showModal();
            onDatesChanged();
        }

        document.querySelectorAll("[data-open-request]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                if (dialog && typeof dialog.showModal === "function") {
                    openDialogAt(null);
                } else {
                    window.location.href = "/leave/request";
                }
            });
        });
        document.querySelectorAll("[data-close-request]").forEach(function (btn) {
            btn.addEventListener("click", function () { if (dialog) dialog.close(); });
        });
        document.querySelectorAll(".dash-day").forEach(function (cell) {
            cell.addEventListener("dblclick", function (e) {
                e.preventDefault();
                var d = cell.getAttribute("data-date");
                if (dialog && typeof dialog.showModal === "function") {
                    openDialogAt(d);
                } else {
                    window.location.href = "/leave/request?date=" + d;
                }
            });
        });

        if (dialog) {
            dialog.addEventListener("close", function () {
                var errorsEl = document.getElementById("previewErrors");
                if (errorsEl) errorsEl.innerHTML = "";
            });
        }

        // ---- 단위 변경: 부분 단위는 종료일을 시작일에 맞추고 읽기 전용으로 ----

        function syncUnitHiddenFields() {
            var active = unitButtons.filter(function (b) { return b.classList.contains("dash-active"); })[0];
            if (!active) return;
            var unitValue = parseFloat(active.getAttribute("data-unit"));
            unitHidden.value = unitValue;
            unitLabelHidden.value = active.getAttribute("data-label");

            if (unitValue !== 1.0) {
                endEl.value = startEl.value;
                endEl.readOnly = true;
                endEl.style.background = "#f3f4f6";
            } else {
                endEl.readOnly = false;
                endEl.style.background = "";
            }
            picker.activeField = "start";
        }

        async function updatePreview() {
            syncUnitHiddenFields();
            updateBadgeAndButton();
            renderMiniCalendar();

            var previewTotal = document.getElementById("previewTotalDays");
            var previewBefore = document.getElementById("previewRemainingBefore");
            var previewAfter = document.getElementById("previewRemainingAfter");
            var previewCount = document.getElementById("previewDateCount");
            var errorsEl = document.getElementById("previewErrors");
            var submitBtn = document.getElementById("submitRequestBtn");
            if (!startEl.value || !endEl.value) return;

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
                if (previewCount) {
                    previewCount.textContent = (data.valid_dates ? data.valid_dates.length : 0) + "건";
                }
                if (previewBefore) previewBefore.textContent = data.remaining_before + "일";
                if (previewAfter) {
                    previewAfter.textContent = data.remaining_after + "일";
                    previewAfter.classList.toggle("dash-bad", data.remaining_after < 0);
                }
                if (absenceBanner) {
                    var names = data.colleague_absences || [];
                    if (names.length) {
                        absenceBanner.textContent = "선택 기간 중 부서 부재: " + names.join(", ");
                        absenceBanner.classList.remove("dash-hidden");
                    } else {
                        absenceBanner.textContent = "";
                        absenceBanner.classList.add("dash-hidden");
                    }
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
                // 네트워크 오류 시 미리보기만 비활성화. 서버 측 검증은 제출 시 그대로 동작한다.
            }
        }

        if (kindEl) kindEl.addEventListener("change", updatePreview);

        // 대시보드 다이얼로그가 아닌 단독 신청 페이지에서는 처음부터 초기화한다.
        if (!dialog) {
            if (startEl.value) {
                var initial = parseDate(startEl.value);
                picker.viewYear = initial.getFullYear();
                picker.viewMonth = initial.getMonth();
            }
            updateBadgeAndButton();
            renderMiniCalendar();
            if (startEl.value && endEl.value) updatePreview();
        }
    });
})();
