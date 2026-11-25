#include "deadlock.hpp"
#include "deadlock_victim.hpp"

#include <cstdlib>
#include <iostream>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAILED: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main() {
    {
        bams::DeadlockDetector detector;
        detector.record_lock_acquired(1, 100);
        detector.record_lock_acquired(2, 200);
        detector.record_lock_wait(1, 2, 200);
        detector.record_lock_wait(2, 1, 100);
        const std::vector<bams::TransactionId> cycle =
            detector.detect_cycle();
        require(
            cycle == std::vector<bams::TransactionId>{1, 2, 1},
            "two-transaction cycle detection"
        );
        require(
            bams::choose_deadlock_victim(cycle) == 2,
            "youngest transaction selected as victim"
        );
    }

    {
        bams::DeadlockDetector detector;
        detector.record_lock_acquired(1, 100);
        detector.record_lock_wait(2, 1, 100);
        require(
            detector.detect_cycle().empty(),
            "acyclic wait-for graph reports no cycle"
        );
    }

    {
        bams::DeadlockDetector detector;
        detector.record_lock_acquired(1, 100);
        detector.record_lock_acquired(2, 200);
        detector.record_lock_acquired(3, 300);
        detector.record_lock_wait(1, 2, 200);
        detector.record_lock_wait(2, 3, 300);
        detector.record_lock_wait(3, 1, 100);
        require(
            detector.detect_cycle()
                == std::vector<bams::TransactionId>{1, 2, 3, 1},
            "three-transaction cycle detection"
        );
    }

    {
        bams::DeadlockDetector detector;
        detector.record_lock_acquired(1, 100);
        detector.record_lock_acquired(2, 200);
        detector.record_lock_wait(1, 2, 200);
        detector.record_lock_wait(2, 1, 100);
        require(!detector.detect_cycle().empty(), "cycle exists before release");
        detector.record_lock_released(2, 200);
        require(
            detector.detect_cycle().empty(),
            "releasing a lock removes its blocking wait edges"
        );
    }

    std::cout << "all deadlock tests passed\n";
    return 0;
}
