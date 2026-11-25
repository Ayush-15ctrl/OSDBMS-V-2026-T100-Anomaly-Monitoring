#include "deadlock.hpp"
#include "deadlock_victim.hpp"

#include <cctype>
#include <cstdint>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using bams::DeadlockDetector;
using bams::StudentId;
using bams::TransactionId;

struct State {
    DeadlockDetector detector;
    std::map<StudentId, TransactionId> owners;
    std::map<std::pair<TransactionId, StudentId>, TransactionId> waits;
};

std::uint64_t parse_id(const std::string& value) {
    if (value.empty()) {
        throw std::invalid_argument("transaction and record ids must be unsigned integers");
    }
    for (char character : value) {
        if (!std::isdigit(static_cast<unsigned char>(character))) {
            throw std::invalid_argument("transaction and record ids must be unsigned integers");
        }
    }
    std::size_t parsed = 0;
    const unsigned long long number = std::stoull(value, &parsed);
    if (parsed != value.size()) {
        throw std::invalid_argument("invalid transaction or record id");
    }
    return static_cast<std::uint64_t>(number);
}

void process_line(const std::string& line, State& state) {
    std::istringstream input(line);
    std::string command;
    std::string transaction_text;
    std::string record_text;
    std::string extra;
    if (!(input >> command >> transaction_text >> record_text) || input >> extra) {
        throw std::invalid_argument("expected exactly: <command> <txn> <record>");
    }

    const TransactionId transaction = parse_id(transaction_text);
    const StudentId record = parse_id(record_text);
    const std::pair<TransactionId, StudentId> wait_key(transaction, record);

    if (command == "acquire") {
        const auto owner = state.owners.find(record);
        if (owner != state.owners.end() && owner->second != transaction) {
            throw std::invalid_argument("cannot acquire a record owned by another transaction");
        }
        state.detector.record_lock_acquired(transaction, record);
        state.owners[record] = transaction;
    } else if (command == "release") {
        const auto owner = state.owners.find(record);
        if (owner == state.owners.end() || owner->second != transaction) {
            throw std::invalid_argument("transaction does not own the record");
        }
        state.detector.record_lock_released(transaction, record);
        state.owners.erase(owner);
    } else if (command == "wait") {
        const auto owner = state.owners.find(record);
        if (owner == state.owners.end() || owner->second == transaction) {
            throw std::invalid_argument("wait requires a different transaction to own the record");
        }
        if (state.waits.find(wait_key) != state.waits.end()) {
            throw std::invalid_argument("transaction is already waiting for the record");
        }
        state.detector.record_lock_wait(transaction, owner->second, record);
        state.waits[wait_key] = owner->second;
    } else if (command == "wait_done") {
        const auto wait = state.waits.find(wait_key);
        if (wait == state.waits.end()) {
            throw std::invalid_argument("transaction has no wait on the record");
        }
        state.detector.record_lock_wait_finished(transaction, wait->second);
        state.waits.erase(wait);
    } else {
        throw std::invalid_argument("unknown command: " + command);
    }
}

void print_result(const std::vector<TransactionId>& detected_cycle) {
    std::vector<TransactionId> cycle = detected_cycle;
    if (cycle.size() > 1 && cycle.front() == cycle.back()) {
        cycle.pop_back();
    }

    std::cout << "{\"cycle\":[";
    for (std::size_t index = 0; index < cycle.size(); ++index) {
        if (index != 0) {
            std::cout << ',';
        }
        std::cout << cycle[index];
    }
    std::cout << "],\"victim\":";
    if (cycle.empty()) {
        std::cout << "null";
    } else {
        std::cout << bams::choose_deadlock_victim(cycle);
    }
    std::cout << "}\n";
}

}  // namespace

int main() {
    State state;
    std::string line;
    try {
        while (std::getline(std::cin, line)) {
            if (line.empty()) {
                throw std::invalid_argument("empty command line");
            }
            process_line(line, state);
        }
    } catch (const std::exception& error) {
        std::cerr << "invalid input: " << error.what() << '\n';
        return 2;
    }

    print_result(state.detector.detect_cycle());
    return 0;
}
