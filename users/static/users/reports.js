import { api, esc, table, select, field, action, download } from './common.js';

function dateLabel(value) {
  if (!value) return null;
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  }).format(new Date(value + 'T00:00:00Z'));
}

function rangeLabel(start, end) {
  if (start && end) return `${dateLabel(start)} – ${dateLabel(end)}`;
  if (start) return `From ${dateLabel(start)}`;
  if (end) return `Through ${dateLabel(end)}`;
  return 'All available dates';
}

function summaryBody(data, filters) {
  const count = data.total_sessions;
  const average = count > 0 ? `${Number(data.average_attendance_percentage).toFixed(2)}%` : '—';
  const range = data.total_sessions > 0 ? (data.date_range || {}) : { start_date: filters.start_date, end_date: filters.end_date };
  return `<div class="report-metrics">
    <div class="report-metric"><span>Average attendance</span><strong>${esc(average)}</strong><small>${count ? 'Across the selected section' : 'Not available without closed sessions'}</small></div>
    <div class="report-metric"><span>Closed sessions</span><strong>${esc(count)}</strong><small>Finalized attendance sessions</small></div>
    <div class="report-metric report-period"><span>Reporting period</span><strong>${esc(rangeLabel(range.start_date, range.end_date))}</strong><small>${count ? 'Dates covered by this summary' : 'Selected date range'}</small></div>
  </div>${count === 0 ? '<div class="report-empty"><h3>No closed sessions in this period</h3><p>Choose a different date range, or close an attendance session before generating its summary.</p></div>' : '<p class="help report-note">Only closed sessions count toward these statistics. Open sessions are still being marked.</p>'}`;
}

function shortageBody(data) {
  const rows = data.students || [];
  if (!rows.length) return `<div class="report-empty"><h3>No students listed below the requirement</h3><p>No shortage entries were returned for this section and date range. Choose another section or broaden the dates to review other attendance.</p></div>`;
  return `<p class="report-count">${rows.length} ${rows.length === 1 ? 'student is' : 'students are'} below the course attendance requirement.</p>` + table(
    ['Student', 'Student number', 'Attendance', 'Required', 'Status'],
    rows.map(row => `<tr><td><strong>${esc(row.student_name)}</strong></td><td>${esc(row.usn || '—')}</td><td>${esc(row.attendance_percentage)}%</td><td>${esc(row.threshold)}%</td><td><span class="badge warn">Below requirement</span></td></tr>`),
  );
}

export function reports(host, sections) {
  if (!sections.length) {
    host.innerHTML = '<section class="card"><h2>Attendance reports</h2><div class="report-empty"><h3>No sections available</h3><p>A section must be available to this account before reports can be generated.</p></div></section>';
    return;
  }
  host.innerHTML = `<section class="card report-card">
    <h2>Attendance reports</h2>
    <p class="muted report-intro">Review a class summary or find students below the attendance requirement.</p>
    <form class="report-filters">
      ${select('Section', 'section_id', sections.map(s => [s.id, s.course.code + ' · ' + s.code]))}
      ${select('Report type', 'type', [['summary', 'Section summary'], ['defaulters', 'Attendance shortages']])}
      ${field('From (optional)', 'start_date', '', 'date')}
      ${field('To (optional)', 'end_date', '', 'date')}
      <div class="report-filter-footer"><p class="help">Leave dates blank to include all available attendance.</p><button>View report</button></div>
    </form>
    <div class="report-result" aria-live="polite"><p class="report-placeholder">Choose a section and report type, then select View report.</p></div>
  </section>`;
  const form = host.querySelector('form');
  const result = host.querySelector('.report-result');
  let sequence = 0;
  form.addEventListener('change', () => {
    sequence += 1;
    result.innerHTML = '<p class="report-placeholder">Filters changed. Select View report to refresh the results.</p>';
  });
  form.onsubmit = event => {
    event.preventDefault();
    action(event.submitter, async () => {
      const filters = Object.fromEntries(new FormData(form));
      if (filters.start_date && filters.end_date && filters.start_date > filters.end_date) {
        result.innerHTML = '<p class="notice error">From date must be on or before To date.</p>';
        return;
      }
      const current = ++sequence;
      const query = new URLSearchParams(Object.entries(filters).filter(([key, value]) => key !== 'type' && value));
      const url = '/api/reports/' + filters.type + '?' + query;
      result.innerHTML = '<p class="loading" role="status">Loading report…</p>';
      try {
        if (filters.type === 'defaulters') {
          const summary = await api('/api/reports/summary?' + query);
          if (current !== sequence) return;
          if (summary.total_sessions === 0) {
            result.innerHTML = `<div class="report-result-header"><div><p class="report-context">${esc(summary.section.course)} · Section ${esc(summary.section.code)}</p><h3>Attendance shortages</h3><p class="help">${esc(rangeLabel(filters.start_date, filters.end_date))}</p></div></div><div class="report-empty"><h3>No closed sessions in this period</h3><p>A shortage report needs finalized attendance. Choose a different date range or close a session first.</p></div>`;
            return;
          }
        }
        const data = await api(url);
        if (current !== sequence) return;
        const summary = filters.type === 'summary';
        result.innerHTML = `<div class="report-result-header">
          <div><p class="report-context">${esc(data.section.course)} · Section ${esc(data.section.code)}</p><h3>${summary ? 'Section summary' : 'Attendance shortages'}</h3>${summary ? '' : `<p class="help">${esc(rangeLabel(filters.start_date, filters.end_date))}</p>`}</div>
          <div class="report-downloads"><button class="secondary small" data-export="csv">Download CSV</button><button class="secondary small" data-export="pdf">Download PDF</button></div>
        </div>${summary ? summaryBody(data, filters) : shortageBody(data)}`;
        result.querySelectorAll('[data-export]').forEach(button => {
          button.onclick = () => action(button, () => download(url + '&export_format=' + button.dataset.export, 'attendease-' + filters.type + '.' + button.dataset.export));
        });
      } catch (error) {
        if (current === sequence) {
          result.innerHTML = `<div class="notice error">${esc(error.message)}<br>Adjust the filters or select View report to try again.</div>`;
        }
      }
    });
  };
}
