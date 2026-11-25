#include "deadlock.hpp"

#include <algorithm>
#include <functional>
#include <map>

namespace bams {

struct DeadlockDetector::WaitEdge {
    TransactionId blocking_transaction;
    StudentId student_id;
    bool owns_lock;
};

DeadlockDetector::DeadlockDetector() = default;

DeadlockDetector::~DeadlockDetector() = default;

void DeadlockDetector::record_lock_acquired(
    TransactionId transaction_id,
    StudentId student_id
) {
    std::vector<WaitEdge>& edges = wait_for_graph_[transaction_id];
    const auto owned = std::find_if(
        edges.begin(),
        edges.end(),
        [student_id](const WaitEdge& edge) {
            return edge.owns_lock && edge.student_id == student_id;
        }
    );
    if (owned == edges.end()) {
        edges.push_back({transaction_id, student_id, true});
    }
}

void DeadlockDetector::record_lock_released(
    TransactionId transaction_id,
    StudentId student_id
) {
    auto owner = wait_for_graph_.find(transaction_id);
    if (owner != wait_for_graph_.end()) {
        std::vector<WaitEdge>& edges = owner->second;
        edges.erase(
            std::remove_if(
                edges.begin(),
                edges.end(),
                [student_id](const WaitEdge& edge) {
                    return edge.owns_lock && edge.student_id == student_id;
                }
            ),
            edges.end()
        );
        if (edges.empty()) {
            wait_for_graph_.erase(owner);
        }
    }

    for (auto waiting = wait_for_graph_.begin();
         waiting != wait_for_graph_.end();) {
        std::vector<WaitEdge>& edges = waiting->second;
        edges.erase(
            std::remove_if(
                edges.begin(),
                edges.end(),
                [transaction_id, student_id](const WaitEdge& edge) {
                    return !edge.owns_lock
                        && edge.blocking_transaction == transaction_id
                        && edge.student_id == student_id;
                }
            ),
            edges.end()
        );
        if (edges.empty()) {
            waiting = wait_for_graph_.erase(waiting);
        } else {
            ++waiting;
        }
    }
}

void DeadlockDetector::record_lock_wait(
    TransactionId waiting_transaction,
    TransactionId blocking_transaction,
    StudentId student_id
) {
    std::vector<WaitEdge>& edges = wait_for_graph_[waiting_transaction];
    const auto existing = std::find_if(
        edges.begin(),
        edges.end(),
        [blocking_transaction, student_id](const WaitEdge& edge) {
            return !edge.owns_lock
                && edge.blocking_transaction == blocking_transaction
                && edge.student_id == student_id;
        }
    );
    if (existing == edges.end()) {
        edges.push_back({blocking_transaction, student_id, false});
    }
}

void DeadlockDetector::record_lock_wait_finished(
    TransactionId waiting_transaction,
    TransactionId blocking_transaction
) {
    auto waiting = wait_for_graph_.find(waiting_transaction);
    if (waiting == wait_for_graph_.end()) {
        return;
    }
    std::vector<WaitEdge>& edges = waiting->second;
    edges.erase(
        std::remove_if(
            edges.begin(),
            edges.end(),
            [blocking_transaction](const WaitEdge& edge) {
                return !edge.owns_lock
                    && edge.blocking_transaction == blocking_transaction;
            }
        ),
        edges.end()
    );
    if (edges.empty()) {
        wait_for_graph_.erase(waiting);
    }
}

std::vector<TransactionId> DeadlockDetector::detect_cycle() const {
    std::map<TransactionId, std::vector<TransactionId>> graph;
    for (const auto& entry : wait_for_graph_) {
        std::vector<TransactionId>& neighbors = graph[entry.first];
        for (const WaitEdge& edge : entry.second) {
            if (!edge.owns_lock) {
                neighbors.push_back(edge.blocking_transaction);
            }
        }
        std::sort(neighbors.begin(), neighbors.end());
        neighbors.erase(
            std::unique(neighbors.begin(), neighbors.end()),
            neighbors.end()
        );
        for (TransactionId neighbor : neighbors) {
            graph[neighbor];
        }
    }

    std::map<TransactionId, int> state;
    std::vector<TransactionId> path;
    std::vector<TransactionId> found;
    std::function<bool(TransactionId)> visit = [&](TransactionId transaction) {
        state[transaction] = 1;
        path.push_back(transaction);
        const std::vector<TransactionId>& neighbors = graph[transaction];
        for (TransactionId neighbor : neighbors) {
            if (state[neighbor] == 0) {
                if (visit(neighbor)) {
                    return true;
                }
            } else if (state[neighbor] == 1) {
                const auto cycle_start = std::find(
                    path.begin(), path.end(), neighbor
                );
                found.assign(cycle_start, path.end());
                found.push_back(neighbor);
                const auto lowest = std::min_element(found.begin(), found.end() - 1);
                std::rotate(found.begin(), lowest, found.end() - 1);
                found.back() = found.front();
                return true;
            }
        }
        path.pop_back();
        state[transaction] = 2;
        return false;
    };

    for (const auto& entry : graph) {
        if (state[entry.first] == 0 && visit(entry.first)) {
            return found;
        }
    }
    return {};
}

}  // namespace bams
