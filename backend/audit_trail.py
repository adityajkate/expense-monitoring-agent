"""
Audit Trail System
Tracks all invoice operations, changes, and access for compliance and forensics
"""

from typing import Dict, List, Optional
from datetime import datetime
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict
import pandas as pd


@dataclass
class AuditEntry:
    """Represents a single audit log entry"""
    entry_id: str
    timestamp: str
    event_type: str
    user_id: str
    invoice_id: Optional[str]
    transaction_id: Optional[str]
    action: str
    details: Dict
    ip_address: Optional[str]
    user_agent: Optional[str]
    status: str  # success, failure, pending
    error_message: Optional[str]


class AuditTrail:
    """
    Comprehensive audit trail system for invoice processing
    Tracks all operations for compliance and forensic analysis
    """

    def __init__(self, storage_path: str = "./data/audit"):
        """
        Initialize audit trail system

        Args:
            storage_path: Directory to store audit logs
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # In-memory cache for recent entries
        self.recent_entries = []
        self.max_cache_size = 1000

        # Event types
        self.EVENT_TYPES = {
            'invoice_upload': 'Invoice uploaded',
            'invoice_processed': 'Invoice processed by OCR',
            'invoice_matched': 'Invoice matched to transaction',
            'invoice_approved': 'Invoice approved for payment',
            'invoice_rejected': 'Invoice rejected',
            'invoice_modified': 'Invoice data modified',
            'invoice_deleted': 'Invoice deleted',
            'fraud_alert': 'Fraud alert triggered',
            'transaction_created': 'Transaction created from invoice',
            'transaction_modified': 'Transaction modified',
            'user_access': 'User accessed invoice',
            'system_action': 'Automated system action',
            'export': 'Data exported',
            'settings_changed': 'System settings changed'
        }

    def log_event(
        self,
        event_type: str,
        action: str,
        user_id: str = "system",
        invoice_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        details: Optional[Dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None
    ) -> str:
        """
        Log an audit event

        Args:
            event_type: Type of event (from EVENT_TYPES)
            action: Description of action taken
            user_id: User who performed action
            invoice_id: Related invoice ID
            transaction_id: Related transaction ID
            details: Additional details as dictionary
            ip_address: User's IP address
            user_agent: User's browser/client
            status: success, failure, or pending
            error_message: Error message if status is failure

        Returns:
            Entry ID of logged event
        """
        entry_id = self._generate_entry_id()
        timestamp = datetime.now().isoformat()

        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=timestamp,
            event_type=event_type,
            user_id=user_id,
            invoice_id=invoice_id,
            transaction_id=transaction_id,
            action=action,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
            error_message=error_message
        )

        # Add to cache
        self.recent_entries.append(entry)
        if len(self.recent_entries) > self.max_cache_size:
            self.recent_entries.pop(0)

        # Persist to disk
        self._persist_entry(entry)

        return entry_id

    def log_invoice_upload(
        self,
        invoice_id: str,
        file_name: str,
        file_size: int,
        user_id: str = "system"
    ) -> str:
        """Log invoice upload event"""
        return self.log_event(
            event_type='invoice_upload',
            action=f'Uploaded invoice: {file_name}',
            user_id=user_id,
            invoice_id=invoice_id,
            details={
                'file_name': file_name,
                'file_size': file_size,
                'file_hash': invoice_id
            }
        )

    def log_invoice_processing(
        self,
        invoice_id: str,
        extraction_data: Dict,
        confidence: float,
        processing_time_ms: float
    ) -> str:
        """Log invoice OCR processing"""
        return self.log_event(
            event_type='invoice_processed',
            action='Invoice processed by OCR',
            invoice_id=invoice_id,
            details={
                'vendor': extraction_data.get('vendor'),
                'amount': extraction_data.get('amounts', {}).get('total'),
                'confidence': confidence,
                'processing_time_ms': processing_time_ms,
                'parser_used': extraction_data.get('parser_used')
            }
        )

    def log_invoice_match(
        self,
        invoice_id: str,
        transaction_id: str,
        match_score: float,
        match_type: str
    ) -> str:
        """Log invoice-to-transaction match"""
        return self.log_event(
            event_type='invoice_matched',
            action=f'Invoice matched to transaction (score: {match_score:.2%})',
            invoice_id=invoice_id,
            transaction_id=transaction_id,
            details={
                'match_score': match_score,
                'match_type': match_type
            }
        )

    def log_fraud_alert(
        self,
        invoice_id: str,
        alert_type: str,
        severity: str,
        confidence: float,
        description: str
    ) -> str:
        """Log fraud detection alert"""
        return self.log_event(
            event_type='fraud_alert',
            action=f'Fraud alert: {alert_type}',
            invoice_id=invoice_id,
            status='pending',
            details={
                'alert_type': alert_type,
                'severity': severity,
                'confidence': confidence,
                'description': description
            }
        )

    def log_invoice_approval(
        self,
        invoice_id: str,
        user_id: str,
        approved: bool,
        reason: Optional[str] = None
    ) -> str:
        """Log invoice approval/rejection"""
        event_type = 'invoice_approved' if approved else 'invoice_rejected'
        action = 'Invoice approved' if approved else 'Invoice rejected'

        return self.log_event(
            event_type=event_type,
            action=action,
            user_id=user_id,
            invoice_id=invoice_id,
            details={
                'approved': approved,
                'reason': reason
            }
        )

    def log_data_modification(
        self,
        invoice_id: str,
        user_id: str,
        field_name: str,
        old_value: any,
        new_value: any,
        reason: Optional[str] = None
    ) -> str:
        """Log manual data modification"""
        return self.log_event(
            event_type='invoice_modified',
            action=f'Modified field: {field_name}',
            user_id=user_id,
            invoice_id=invoice_id,
            details={
                'field_name': field_name,
                'old_value': str(old_value),
                'new_value': str(new_value),
                'reason': reason
            }
        )

    def get_invoice_history(self, invoice_id: str) -> List[Dict]:
        """
        Get complete audit history for an invoice

        Args:
            invoice_id: Invoice ID to query

        Returns:
            List of audit entries for this invoice
        """
        # Search in cache first
        cache_entries = [
            asdict(entry) for entry in self.recent_entries
            if entry.invoice_id == invoice_id
        ]

        # Search in persisted logs
        persisted_entries = self._search_persisted_logs({'invoice_id': invoice_id})

        # Combine and deduplicate
        all_entries = cache_entries + persisted_entries
        seen_ids = set()
        unique_entries = []

        for entry in all_entries:
            if entry['entry_id'] not in seen_ids:
                seen_ids.add(entry['entry_id'])
                unique_entries.append(entry)

        # Sort by timestamp
        unique_entries.sort(key=lambda x: x['timestamp'], reverse=True)

        return unique_entries

    def get_user_activity(
        self,
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Get all activity for a specific user

        Args:
            user_id: User ID to query
            start_date: Optional start date (ISO format)
            end_date: Optional end date (ISO format)

        Returns:
            List of audit entries for this user
        """
        filters = {'user_id': user_id}
        if start_date:
            filters['start_date'] = start_date
        if end_date:
            filters['end_date'] = end_date

        return self._search_persisted_logs(filters)

    def get_fraud_alerts(
        self,
        severity: Optional[str] = None,
        start_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Get all fraud alerts

        Args:
            severity: Filter by severity (critical, high, medium, low)
            start_date: Optional start date

        Returns:
            List of fraud alert entries
        """
        filters = {'event_type': 'fraud_alert'}
        if start_date:
            filters['start_date'] = start_date

        alerts = self._search_persisted_logs(filters)

        # Filter by severity if specified
        if severity:
            alerts = [
                alert for alert in alerts
                if alert.get('details', {}).get('severity') == severity
            ]

        return alerts

    def generate_compliance_report(
        self,
        start_date: str,
        end_date: str
    ) -> Dict:
        """
        Generate compliance report for date range

        Args:
            start_date: Start date (ISO format)
            end_date: End date (ISO format)

        Returns:
            Compliance report with statistics
        """
        filters = {
            'start_date': start_date,
            'end_date': end_date
        }

        entries = self._search_persisted_logs(filters)

        # Calculate statistics
        total_events = len(entries)
        events_by_type = {}
        events_by_user = {}
        failed_events = []
        fraud_alerts = []

        for entry in entries:
            # Count by type
            event_type = entry.get('event_type', 'unknown')
            events_by_type[event_type] = events_by_type.get(event_type, 0) + 1

            # Count by user
            user_id = entry.get('user_id', 'unknown')
            events_by_user[user_id] = events_by_user.get(user_id, 0) + 1

            # Track failures
            if entry.get('status') == 'failure':
                failed_events.append(entry)

            # Track fraud alerts
            if event_type == 'fraud_alert':
                fraud_alerts.append(entry)

        return {
            'report_period': {
                'start_date': start_date,
                'end_date': end_date
            },
            'summary': {
                'total_events': total_events,
                'unique_users': len(events_by_user),
                'failed_events': len(failed_events),
                'fraud_alerts': len(fraud_alerts)
            },
            'events_by_type': events_by_type,
            'events_by_user': events_by_user,
            'top_users': sorted(
                events_by_user.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10],
            'failed_events': failed_events[:50],  # Top 50 failures
            'fraud_alerts': fraud_alerts
        }

    def export_audit_log(
        self,
        output_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        format: str = 'csv'
    ) -> str:
        """
        Export audit log to file

        Args:
            output_path: Path to output file
            start_date: Optional start date
            end_date: Optional end date
            format: Output format (csv, json)

        Returns:
            Path to exported file
        """
        filters = {}
        if start_date:
            filters['start_date'] = start_date
        if end_date:
            filters['end_date'] = end_date

        entries = self._search_persisted_logs(filters)

        # Log export event
        self.log_event(
            event_type='export',
            action=f'Exported audit log ({len(entries)} entries)',
            details={
                'output_path': output_path,
                'format': format,
                'entry_count': len(entries)
            }
        )

        if format == 'csv':
            df = pd.DataFrame(entries)
            df.to_csv(output_path, index=False)
        elif format == 'json':
            with open(output_path, 'w') as f:
                json.dump(entries, f, indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")

        return output_path

    def _persist_entry(self, entry: AuditEntry):
        """Persist audit entry to disk"""
        # Organize by date for efficient querying
        date_str = entry.timestamp[:10]  # YYYY-MM-DD
        log_file = self.storage_path / f"audit_{date_str}.jsonl"

        # Append to JSONL file
        with open(log_file, 'a') as f:
            f.write(json.dumps(asdict(entry)) + '\n')

    def _search_persisted_logs(self, filters: Dict) -> List[Dict]:
        """Search persisted log files"""
        results = []

        # Determine which files to search
        if 'start_date' in filters or 'end_date' in filters:
            # Search specific date range
            start = filters.get('start_date', '2000-01-01')[:10]
            end = filters.get('end_date', '2099-12-31')[:10]

            for log_file in self.storage_path.glob('audit_*.jsonl'):
                file_date = log_file.stem.replace('audit_', '')
                if start <= file_date <= end:
                    results.extend(self._read_log_file(log_file, filters))
        else:
            # Search all files
            for log_file in self.storage_path.glob('audit_*.jsonl'):
                results.extend(self._read_log_file(log_file, filters))

        return results

    def _read_log_file(self, log_file: Path, filters: Dict) -> List[Dict]:
        """Read and filter entries from a log file"""
        results = []

        try:
            with open(log_file, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())

                        # Apply filters
                        if self._matches_filters(entry, filters):
                            results.append(entry)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass

        return results

    def _matches_filters(self, entry: Dict, filters: Dict) -> bool:
        """Check if entry matches all filters"""
        for key, value in filters.items():
            if key in ['start_date', 'end_date']:
                continue  # Already handled by file selection

            if entry.get(key) != value:
                return False

        return True

    def _generate_entry_id(self) -> str:
        """Generate unique entry ID"""
        timestamp = datetime.now().isoformat()
        return hashlib.sha256(timestamp.encode()).hexdigest()[:16]


if __name__ == "__main__":
    """Test audit trail system"""
    print("=" * 80)
    print("AUDIT TRAIL SYSTEM TEST")
    print("=" * 80)

    audit = AuditTrail(storage_path="./test_audit")

    # Log some events
    print("\nLogging events...")

    entry1 = audit.log_invoice_upload(
        invoice_id='inv001',
        file_name='invoice.pdf',
        file_size=102400,
        user_id='user123'
    )
    print(f"  Logged upload: {entry1}")

    entry2 = audit.log_invoice_processing(
        invoice_id='inv001',
        extraction_data={
            'vendor': 'AWS',
            'amounts': {'total': 1500.00},
            'parser_used': 'intelligent'
        },
        confidence=0.95,
        processing_time_ms=2500
    )
    print(f"  Logged processing: {entry2}")

    entry3 = audit.log_fraud_alert(
        invoice_id='inv001',
        alert_type='suspicious_amount',
        severity='medium',
        confidence=0.75,
        description='Amount higher than usual'
    )
    print(f"  Logged fraud alert: {entry3}")

    # Query history
    print("\nQuerying invoice history...")
    history = audit.get_invoice_history('inv001')
    print(f"  Found {len(history)} entries for inv001")

    for entry in history:
        print(f"    [{entry['timestamp']}] {entry['action']}")

    print("\nAudit trail system ready!")
