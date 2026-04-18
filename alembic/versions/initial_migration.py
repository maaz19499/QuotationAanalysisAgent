"""Initial migration

Revision ID: 000000000001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '000000000001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create enum types
    processing_status = postgresql.ENUM(
        'pending', 'processing', 'completed', 'failed', 'partial',
        name='processingstatus'
    )
    processing_status.create(op.get_bind())

    confidence_level = postgresql.ENUM(
        'high', 'medium', 'low', 'uncertain',
        name='extractionconfidence'
    )
    confidence_level.create(op.get_bind())

    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(length=50), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'PARTIAL', name='processingstatus'), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('processing_started_at', sa.DateTime(), nullable=True),
        sa.Column('processing_completed_at', sa.DateTime(), nullable=True),
        sa.Column('processing_time_seconds', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create extraction_results table
    op.create_table(
        'extraction_results',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('document_id', postgresql.UUID(), nullable=False),
        sa.Column('supplier_name', sa.String(length=255), nullable=True),
        sa.Column('supplier_name_confidence', sa.Float(), nullable=True),
        sa.Column('quotation_number', sa.String(length=100), nullable=True),
        sa.Column('quotation_number_confidence', sa.Float(), nullable=True),
        sa.Column('quotation_date', sa.String(length=50), nullable=True),
        sa.Column('quotation_date_confidence', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('subtotal', sa.Float(), nullable=True),
        sa.Column('tax_amount', sa.Float(), nullable=True),
        sa.Column('total_amount', sa.Float(), nullable=True),
        sa.Column('total_confidence', sa.Float(), nullable=True),
        sa.Column('raw_extracted_data', postgresql.JSONB(), nullable=True),
        sa.Column('extraction_errors', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id')
    )

    # Create line_items table
    op.create_table(
        'line_items',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('extraction_result_id', postgresql.UUID(), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=True),
        sa.Column('product_code', sa.String(length=100), nullable=True),
        sa.Column('product_code_confidence', sa.Float(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('description_confidence', sa.Float(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('quantity_confidence', sa.Float(), nullable=True),
        sa.Column('unit_of_measure', sa.String(length=50), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('unit_price_confidence', sa.Float(), nullable=True),
        sa.Column('total_price', sa.Float(), nullable=True),
        sa.Column('total_price_confidence', sa.Float(), nullable=True),
        sa.Column('overall_confidence', sa.Float(), nullable=False),
        sa.Column('confidence_level', sa.Enum('HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN', name='extractionconfidence'), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['extraction_result_id'], ['extraction_results.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_documents_status', 'documents', ['status'])
    op.create_index('ix_documents_uploaded_at', 'documents', ['uploaded_at'])
    op.create_index('ix_line_items_extraction_result_id', 'line_items', ['extraction_result_id'])
    op.create_index('ix_line_items_overall_confidence', 'line_items', ['overall_confidence'])


def downgrade():
    op.drop_index('ix_line_items_overall_confidence')
    op.drop_index('ix_line_items_extraction_result_id')
    op.drop_index('ix_documents_uploaded_at')
    op.drop_index('ix_documents_status')

    op.drop_table('line_items')
    op.drop_table('extraction_results')
    op.drop_table('documents')

    postgresql.ENUM(name='processingstatus').drop(op.get_bind())
    postgresql.ENUM(name='extractionconfidence').drop(op.get_bind())
