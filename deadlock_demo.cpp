#include "deadlock.hpp"
#include "deadlock_victim.hpp"

#include <iostream>
#include <string>
#include <vector>

namespace {

void print_cycle(const std::vector<bams::TransactionId>& cycle) {
    for (std::size_t index = 0; index < cycle.size(); ++index) {
        if (index != 0) {
            std::cout << " -> ";
        }
        std::cout << "T" << cycle[index];
    }
    std::cout << '\n';
}

bool two_transaction_case() {
    bams::DeadlockDetector detector;
    detector.record_lock_acquired(1, 100);
    detector.record_lock_acquired(2, 200);
    detector.record_lock_wait(1, 2, 200);
    detector.record_lock_wait(2, 1, 100);

    std::cout << "two-transaction wait-for edges: T1 -> T2, T2 -> T1\n";
    const std::vector<bams::TransactionId> cycle = detector.detect_cycle();
    if (cycle != std::vector<bams::TransactionId>{1, 2, 1}) {
        std::cerr << "two-transaction scenario failed: expected cycle T1 -> T2 -> T1\n";
        return false;
    }
    std::cout << "two-transaction cycle: ";
    print_cycle(cycle);

    const bams::TransactionId victim = bams::choose_deadlock_victim(cycle);
    if (victim != 2) {
        std::cerr << "two-transaction scenario failed: expected victim T2\n";
        return false;
    }
    std::cout << "victim: T" << victim
              << " (youngest transaction: highest transaction id)\n";
    detector.record_lock_wait_finished(victim, 1);
    detector.record_lock_released(victim, 200);
    std::cout << "abort: T" << victim << " aborted\n";
    detector.record_lock_wait_finished(1, victim);
    detector.record_lock_acquired(1, 200);
    detector.record_lock_released(1, 200);
    detector.record_lock_released(1, 100);
    std::cout << "survivor: T1 acquired B and finished\n";
    return detector.detect_cycle().empty();
}

bool same_order_case() {
    bams::DeadlockDetector detector;
    detector.record_lock_acquired(1, 100);
    detector.record_lock_wait(2, 1, 100);
    detector.record_lock_acquired(1, 200);

    const std::vector<bams::TransactionId> cycle = detector.detect_cycle();
    if (!cycle.empty()) {
        std::cerr << "same-order scenario failed: unexpected cycle\n";
        return false;
    }
    std::cout << "same-order case: no cycle\n";

    detector.record_lock_released(1, 200);
    detector.record_lock_released(1, 100);
    detector.record_lock_wait_finished(2, 1);
    detector.record_lock_acquired(2, 100);
    detector.record_lock_acquired(2, 200);
    detector.record_lock_released(2, 200);
    detector.record_lock_released(2, 100);
    return true;
}

bool three_transaction_case() {
    bams::DeadlockDetector detector;
    detector.record_lock_acquired(1, 100);
    detector.record_lock_acquired(2, 200);
    detector.record_lock_acquired(3, 300);
    detector.record_lock_wait(1, 2, 200);
    detector.record_lock_wait(2, 3, 300);
    detector.record_lock_wait(3, 1, 100);

    const std::vector<bams::TransactionId> cycle = detector.detect_cycle();
    if (cycle != std::vector<bams::TransactionId>{1, 2, 3, 1}) {
        std::cerr << "three-transaction scenario failed: unexpected cycle\n";
        return false;
    }
    std::cout << "three-transaction cycle: ";
    print_cycle(cycle);
    const bams::TransactionId victim = bams::choose_deadlock_victim(cycle);
    if (victim != 3) {
        std::cerr << "three-transaction scenario failed: expected victim T3\n";
        return false;
    }
    std::cout << "three-transaction victim: T" << victim
              << " (youngest transaction: highest transaction id)\n";
    return true;
}

}  // namespace

int main() {
    if (!two_transaction_case()) {
        return 1;
    }
    if (!same_order_case()) {
        return 1;
    }
    if (!three_transaction_case()) {
        return 1;
    }
    return 0;
}
