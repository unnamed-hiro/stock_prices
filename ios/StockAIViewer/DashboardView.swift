// DashboardView.swift — 口座サマリー: 評価額・リターン・資産推移グラフ・保有銘柄

import SwiftUI
import Charts

struct DashboardView: View {
    @State private var state: PortfolioState?
    @State private var error: String?
    @State private var loading = false

    var body: some View {
        NavigationStack {
            Group {
                if let s = state {
                    content(s)
                } else if let e = error {
                    ContentUnavailableView("取得エラー", systemImage: "wifi.exclamationmark",
                                           description: Text(e))
                } else {
                    ProgressView("読み込み中...")
                }
            }
            .navigationTitle("AI運用口座")
            .refreshable { await load() }
            .task { if state == nil { await load() } }
        }
    }

    @ViewBuilder
    private func content(_ s: PortfolioState) -> some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text(yen(s.currentEquity))
                        .font(.system(size: 34, weight: .bold, design: .rounded))
                    HStack(spacing: 12) {
                        Label(pct(s.returnPct),
                              systemImage: s.returnPct >= 0 ? "arrow.up.right" : "arrow.down.right")
                            .foregroundStyle(s.returnPct >= 0 ? .green : .red)
                            .font(.headline)
                        Text("投下資本 \(yen(s.investedCapital))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if s.totalDeposits > 0 {
                        Text("(積立入金 \(yen(s.totalDeposits)) は利益に含めず計算)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }

            Section("資産推移") {
                if s.equityCurve.count >= 2 {
                    Chart(s.equityCurve) { p in
                        LineMark(x: .value("日付", p.date), y: .value("評価額", p.value))
                            .interpolationMethod(.monotone)
                        AreaMark(x: .value("日付", p.date), y: .value("評価額", p.value))
                            .opacity(0.12)
                    }
                    .chartYScale(domain: .automatic(includesZero: false))
                    .frame(height: 220)
                    .padding(.vertical, 4)
                } else {
                    Text("データがまだありません").foregroundStyle(.secondary)
                }
            }

            Section("現金・取引") {
                LabeledContent("現金残", value: yen(s.cash))
                LabeledContent("総取引数", value: "\(s.trades.count)回")
                let sells = s.trades.filter { $0.side == "sell" }
                if !sells.isEmpty {
                    let wins = sells.filter { $0.pnl > 0 }.count
                    LabeledContent("決済 / 勝率",
                                   value: "\(sells.count)回 / \(wins * 100 / sells.count)%")
                }
            }

            Section("保有銘柄 (\(s.positions.count))") {
                ForEach(s.positions.values.sorted { $0.ticker < $1.ticker }) { p in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(p.ticker).font(.headline)
                            Text("取得 \(String(p.entryDate.prefix(10)))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        VStack(alignment: .trailing) {
                            Text("\(p.shares)株")
                            Text("@\(yen(p.entryPrice))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            state = try await GitHubClient()
                .file("data/state/portfolio.json", as: PortfolioState.self)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
