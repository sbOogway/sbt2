//! Decodes Arrow IPC streams into the plain types of `results`.

use std::io::Cursor;

use arrow_array::{
    Array, ArrayRef, ArrowPrimitiveType, RecordBatch,
    cast::AsArray,
    types::{
        Float32Type, Float64Type, Int8Type, Int16Type, Int32Type, Int64Type,
        TimestampMicrosecondType, TimestampMillisecondType, TimestampNanosecondType,
        TimestampSecondType, UInt8Type, UInt16Type, UInt32Type, UInt64Type,
    },
};
use arrow_ipc::reader::StreamReader;
use arrow_schema::{DataType, TimeUnit};

use crate::{Cell, ClientError, Point, Table};

pub(crate) fn points(
    data: &[u8],
    time_column: &str,
    value_column: &str,
) -> Result<Vec<Point>, ClientError> {
    let table = table(data)?;
    let time = column_position(&table, time_column)?;
    let value = column_position(&table, value_column)?;
    table
        .rows
        .into_iter()
        .map(|row| point(&row[time], &row[value]))
        .collect()
}

pub(crate) fn table(data: &[u8]) -> Result<Table, ClientError> {
    let reader = StreamReader::try_new(Cursor::new(data), None).map_err(invalid)?;
    let columns = reader
        .schema()
        .fields()
        .iter()
        .map(|field| field.name().clone())
        .collect();
    let mut rows = Vec::new();
    for batch in reader {
        rows.extend(batch_rows(&batch.map_err(invalid)?)?);
    }
    Ok(Table { columns, rows })
}

fn column_position(table: &Table, name: &str) -> Result<usize, ClientError> {
    table
        .columns
        .iter()
        .position(|column| column == name)
        .ok_or_else(|| ClientError::Protocol(format!("the Arrow stream has no column {name}")))
}

fn point(time: &Cell, value: &Cell) -> Result<Point, ClientError> {
    let Cell::Time(ts) = time else {
        return Err(ClientError::Protocol(format!("not a time: {time:?}")));
    };
    let value = match value {
        Cell::Float(value) => *value,
        Cell::Int(value) => *value as f64,
        Cell::Null => f64::NAN,
        other => return Err(ClientError::Protocol(format!("not a number: {other:?}"))),
    };
    Ok(Point { ts: *ts, value })
}

fn batch_rows(batch: &RecordBatch) -> Result<Vec<Vec<Cell>>, ClientError> {
    let columns = batch
        .columns()
        .iter()
        .map(column_cells)
        .collect::<Result<Vec<_>, _>>()?;
    Ok((0..batch.num_rows())
        .map(|row| columns.iter().map(|cells| cells[row].clone()).collect())
        .collect())
}

fn column_cells(array: &ArrayRef) -> Result<Vec<Cell>, ClientError> {
    Ok(match array.data_type() {
        DataType::Null => vec![Cell::Null; array.len()],
        DataType::Boolean => options(array.as_boolean().iter(), Cell::Bool),
        DataType::Int8 => integers::<Int8Type>(array),
        DataType::Int16 => integers::<Int16Type>(array),
        DataType::Int32 => integers::<Int32Type>(array),
        DataType::Int64 => integers::<Int64Type>(array),
        DataType::UInt8 => integers::<UInt8Type>(array),
        DataType::UInt16 => integers::<UInt16Type>(array),
        DataType::UInt32 => integers::<UInt32Type>(array),
        DataType::UInt64 => options(array.as_primitive::<UInt64Type>().iter(), unsigned),
        DataType::Float32 => options(array.as_primitive::<Float32Type>().iter(), |value| {
            Cell::Float(f64::from(value))
        }),
        DataType::Float64 => options(array.as_primitive::<Float64Type>().iter(), Cell::Float),
        DataType::Utf8 => options(array.as_string::<i32>().iter(), |text| {
            Cell::Text(text.to_owned())
        }),
        DataType::LargeUtf8 => options(array.as_string::<i64>().iter(), |text| {
            Cell::Text(text.to_owned())
        }),
        DataType::Timestamp(unit, _) => times(array, *unit),
        other => {
            return Err(ClientError::Protocol(format!(
                "unsupported Arrow column type {other}"
            )));
        }
    })
}

fn options<T>(values: impl Iterator<Item = Option<T>>, cell: impl Fn(T) -> Cell) -> Vec<Cell> {
    values
        .map(|value| value.map_or(Cell::Null, &cell))
        .collect()
}

fn integers<T>(array: &ArrayRef) -> Vec<Cell>
where
    T: ArrowPrimitiveType,
    T::Native: Into<i64>,
{
    options(array.as_primitive::<T>().iter(), |value| {
        Cell::Int(value.into())
    })
}

fn unsigned(value: u64) -> Cell {
    i64::try_from(value).map_or(Cell::Float(value as f64), Cell::Int)
}

fn times(array: &ArrayRef, unit: TimeUnit) -> Vec<Cell> {
    match unit {
        TimeUnit::Second => scaled_times::<TimestampSecondType>(array, 1_000_000_000),
        TimeUnit::Millisecond => scaled_times::<TimestampMillisecondType>(array, 1_000_000),
        TimeUnit::Microsecond => scaled_times::<TimestampMicrosecondType>(array, 1_000),
        TimeUnit::Nanosecond => scaled_times::<TimestampNanosecondType>(array, 1),
    }
}

fn scaled_times<T>(array: &ArrayRef, nanoseconds_per_tick: i64) -> Vec<Cell>
where
    T: ArrowPrimitiveType<Native = i64>,
{
    options(array.as_primitive::<T>().iter(), |ticks| {
        Cell::Time(ticks.saturating_mul(nanoseconds_per_tick))
    })
}

fn invalid(error: arrow_schema::ArrowError) -> ClientError {
    ClientError::Protocol(format!("invalid Arrow stream: {error}"))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::{
        ArrayRef, BooleanArray, Float64Array, Int64Array, RecordBatch, StringArray,
        TimestampNanosecondArray,
    };
    use arrow_ipc::writer::StreamWriter;
    use arrow_schema::{Field, Schema};

    use super::*;
    use crate::Cell;

    fn stream(columns: Vec<(&str, ArrayRef)>) -> Vec<u8> {
        let fields: Vec<_> = columns
            .iter()
            .map(|(name, array)| Field::new(*name, array.data_type().clone(), true))
            .collect();
        let schema = Arc::new(Schema::new(fields));
        let arrays = columns.into_iter().map(|(_, array)| array).collect();
        let batch = RecordBatch::try_new(Arc::clone(&schema), arrays).unwrap();
        let mut bytes = Vec::new();
        let mut writer = StreamWriter::try_new(&mut bytes, &schema).unwrap();
        writer.write(&batch).unwrap();
        writer.finish().unwrap();
        bytes
    }

    fn times(values: &[i64]) -> ArrayRef {
        Arc::new(TimestampNanosecondArray::from(values.to_vec()).with_timezone("UTC"))
    }

    fn floats(values: &[Option<f64>]) -> ArrayRef {
        Arc::new(Float64Array::from(values.to_vec()))
    }

    #[test]
    fn points_decode_their_timestamps_and_values() {
        let data = stream(vec![
            ("ts", times(&[1_000, 2_000])),
            ("value", floats(&[Some(0.5), Some(-1.25)])),
        ]);

        let decoded = points(&data, "ts", "value").unwrap();

        let expected = [(1_000, 0.5), (2_000, -1.25)];
        let expected: Vec<_> = expected
            .into_iter()
            .map(|(ts, value)| Point { ts, value })
            .collect();
        assert_eq!(decoded, expected);
    }

    #[test]
    fn a_null_or_nan_value_decodes_as_nan() {
        let data = stream(vec![
            ("ts", times(&[1, 2, 3])),
            ("value", floats(&[None, Some(f64::NAN), Some(1.0)])),
        ]);

        let decoded = points(&data, "ts", "value").unwrap();

        assert!(decoded[0].value.is_nan() && decoded[1].value.is_nan());
        assert_eq!(decoded[2].value, 1.0);
    }

    #[test]
    fn an_empty_stream_with_its_columns_is_no_points() {
        let data = stream(vec![("ts", times(&[])), ("value", floats(&[]))]);

        assert_eq!(points(&data, "ts", "value").unwrap(), []);
    }

    #[test]
    fn a_stream_without_the_expected_columns_is_a_protocol_error() {
        let data = stream(vec![("ts", times(&[1])), ("other", floats(&[Some(1.0)]))]);

        let result = points(&data, "ts", "value");

        assert!(
            matches!(result, Err(ClientError::Protocol(_))),
            "{result:?}"
        );
        assert!(matches!(
            points(b"not arrow", "ts", "value"),
            Err(ClientError::Protocol(_))
        ));
    }

    #[test]
    fn a_table_keeps_its_column_names_order_and_cell_types() {
        let ids: ArrayRef = Arc::new(Int64Array::from(vec![Some(7), None]));
        let sides: ArrayRef = Arc::new(StringArray::from(vec!["BUY", "SELL"]));
        let flags: ArrayRef = Arc::new(BooleanArray::from(vec![true, false]));
        let data = stream(vec![
            ("id", ids),
            ("price", floats(&[Some(1.5), Some(2.5)])),
            ("side", sides),
            ("ts_event", times(&[10, 20])),
            ("open", flags),
        ]);

        let decoded = table(&data).unwrap();

        assert_eq!(decoded.columns, ["id", "price", "side", "ts_event", "open"]);
        let text = |value: &str| Cell::Text(value.to_owned());
        assert_eq!(
            decoded.rows,
            [
                vec![
                    Cell::Int(7),
                    Cell::Float(1.5),
                    text("BUY"),
                    Cell::Time(10),
                    Cell::Bool(true),
                ],
                vec![
                    Cell::Null,
                    Cell::Float(2.5),
                    text("SELL"),
                    Cell::Time(20),
                    Cell::Bool(false),
                ],
            ]
        );
    }
}
