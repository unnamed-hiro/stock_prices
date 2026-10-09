// MonthlyReportsView.swift — 月次成績表 (α・勝率・損益レシオ・リスク管理の発動)

import SwiftUI

struct MonthlyReportsView: View {
    @State private var reports: [MonthlyReport] = []
    @State private var error: String?
    @State private var empty = false

    var body: some View {
        NavigationStack {
            Group {
                if empty {
                    ContentUnavailableView(
                        "まだ月次レポートがありません", systemImage: "calendar.badge.clock",
                        description: Text("毎月1日に前月分が自動生成されます"))
                } else if reports.isEmpty, let e = error {
                    ContentUnavailableView("取得エラー", systemImage: "wifi.exclamationmark",
                                           description: Text(e))
                } else if reports.isEmpty {
                    ProgressView("読み込み中...")
                } else {
                    List(reports) { r in
                        Section(r.month) { monthlyRows(r) }
                    }
                }
            }
            .navigationTitle("月次成績")
            .refreshable { await load() }
            .task { if reports.isEmpty { await load() } }
        }
    }

    @ViewBuilder
    private func monthlyRows(_ r: MonthlyReport) -> some View {
        LabeledContent("当月損益") {
            Text("\(yen(r.profit)) (\(pct(r.monthReturnPct)))")
                .foregroundStyle(r.profit >= 0 ? .green : .red)
        }
        LabeledContent("市場 (全銘柄等ウェイト)", value: pct(r.benchmarkPct))
        LabeledContent("α (市場超過)") {
            Text(pct(r.alphaPct))
                .bold()
                .foregroundStyle((r.alphaPct ?? 0) >= 0 ? .green : .red)
        }
        LabeledContent("累計リターン", value: pct(r.cumulativeReturnPct))
        if r.depositsInMonth > 0 {
            LabeledContent("当月積立", value: yen(r.depositsInMonth))
        }
        LabeledContent("決済 / 勝率",
                       value: "\(r.nClosed)回 / \(r.winRatePct.map { String(format: "%.0f%%", $0) } ?? "—")")
        if let p = r.payoffRatio {
            LabeledContent("損益レシオ", value: String(format: "%.2f", p))
        }
        LabeledContent("リスクオフ日数", value: "\(r.riskOffDays) / \(r.tradingDays)営業日")
        LabeledContent("決算またぎ回避", value: "\(r.earningsSkips)回")
    }

    private func load() async {
        do {
            let files = try await GitHubClient().list("results/monthly")
            let months = files.filter { $0.name.hasSuffix(".json") }
                              .sorted { $0.name > $1.name }
            if months.isEmpty { empty = true; return }
            var out: [MonthlyReport] = []
            for f in months.prefix(12) {
                out.append(try await GitHubClient().file(f.path, as: MonthlyReport.self))
            }
            reports = out
            error = nil
        } catch GitHubError.http(404) {
            empty = true
        } catch {
            self.error = error.localizedDescription
        }
    }
}
