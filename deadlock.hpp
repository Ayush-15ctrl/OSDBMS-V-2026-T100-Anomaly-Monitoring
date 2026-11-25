#pragma once

#include <cstdint>
#include <unordered_map>
#include <vector>

namespace bams {

using TransactionId = std::uint64_t;
using StudentId = std::uint64_t;

class DeadlockDetector {
public:
    DeadlockDetector();
    ~DeadlockDetector();

    // Records that a transaction currently owns the lock for a student.
    void record_lock_acquired(TransactionId transaction_id, StudentId student_id);

    // Removes ownership when the transaction releases the student lock.
    void record_lock_released(TransactionId transaction_id, StudentId student_id);

    // Records a wait edge while a transaction is blocked by another owner.
    void record_lock_wait(TransactionId waiting_transaction,
                          TransactionId blocking_transaction,
                          StudentId student_id);

    // Removes a previously recorded wait edge after acquisition or cancellation.
    void record_lock_wait_finished(TransactionId waiting_transaction,
                                   TransactionId blocking_transaction);

    // Runs DFS over the wait-for graph and returns one transaction cycle, if present.
    std::vector<TransactionId> detect_cycle() const;

private:
    struct WaitEdge;

    // Not thread-safe. The caller (the lock manager) must serialize access.
    std::unordered_map<TransactionId, std::vector<WaitEdge>> wait_for_graph_;
};

}  // namespace bams
